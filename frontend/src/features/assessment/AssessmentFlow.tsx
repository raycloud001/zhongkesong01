import { useEffect, useRef, useState } from 'react';
import { ApiError, createSession, ensureIdentity, getCurrent, getSession, saveAnswer, sendEvent, submitSession, type Question, type Session } from './api';
import { cacheKey, mergeServerDraft, updateAnswer, type AnswerValue, type DraftState } from './state';

const fieldLabels:Record<string,string>={choice:'选项',reason:'原因',name:'名称',frequency:'使用频率',typicalTask:'典型任务',independence:'独立程度',work:'作品或项目',action:'你的动作',result:'结果或反馈',time:'时间',status:'经历状态',goal:'目标',target:'目标任务',text:'文字说明'};
const OPTION_ANIMATION_MS=280;
type PromptOption={id:string;label:string};
const questionOptions=(question:Question):readonly PromptOption[]=>question.options?.length?question.options:(question.fields?.find(field=>field.options?.length)?.options??[]);
const present=(value:unknown)=>value!==undefined&&value!==''&&(!(typeof value==='string')||value.trim().length>0)&&(!Array.isArray(value)||value.length>0);
const validNumber=(value:unknown,min=-Infinity,max=Infinity)=>typeof value==='number'&&Number.isFinite(value)&&value>=min&&value<=max;
const validSingle=(value:unknown,options:readonly {id:string}[])=>typeof value==='string'&&options.some(option=>option.id===value);
const validMultiple=(value:unknown,options:readonly {id:string}[],minimum:number,maximum:number)=>Array.isArray(value)&&value.every(item=>typeof item==='string')&&new Set(value).size===value.length&&value.length>=minimum&&value.length<=maximum&&value.every(item=>options.some(option=>option.id===item));
const validFieldValue=(field:NonNullable<Question['fields']>[number],value:unknown)=>{
  if(field.type==='single')return validSingle(value,field.options??[]);
  if(field.type==='multiple')return validMultiple(value,field.options??[],field.minSelections??1,field.maxSelections??field.options?.length??0);
  if(field.type==='integer')return validNumber(value,field.min??-Infinity,field.max??Infinity)&&Number.isInteger(value);
  if(field.type==='text')return typeof value==='string'&&value.length<=(field.maxLength??10_000);
  if(field.type==='audio')return field.status!=='pending_implementation'&&typeof value==='string';
  if(field.type==='scale')return validNumber(value,field.min??-Infinity,field.max??Infinity);
  return typeof value==='string'&&value.length<=(field.maxLength??10_000);
};
export const questionComplete=(question:Question,value:AnswerValue|undefined)=>{
  if(!present(value))return !question.required;
  if(question.type!=='compound'){
    if(question.type==='single')return validSingle(value,questionOptions(question));
    if(question.type==='multiple'){
      const field=question.fields?.find(candidate=>candidate.type==='multiple');
      const options=questionOptions(question);
      const minimum=field?.minSelections??question.minSelections??(question.required?1:0);
      const maximum=field?.maxSelections??question.maxSelections??options.length;
      return validMultiple(value,options,minimum,maximum);
    }
    if(question.type==='scale')return validNumber(value,question.min??-Infinity,question.max??Infinity);
    return typeof value==='string'&&value.length<=(question.maxLength??10_000);
  }
  if(typeof value!=='object'||Array.isArray(value))return false;
  const object=value as Record<string,unknown>,fields=question.fields??[];
  if(Object.keys(object).some(key=>!fields.some(field=>field.id===key)))return false;
  if(!fields.every(field=>{
    const active=!field.condition||object[field.condition.field]===field.condition.equals;
    const fieldValue=object[field.id];
    if(!active)return fieldValue===undefined;
    if(!present(fieldValue))return !(field.required||field.requiredWhenCondition);
    return validFieldValue(field,fieldValue);
  }))return false;
  const combined=fields.find(field=>field.combinedLength&&(!field.condition||object[field.condition.field]===field.condition.equals))?.combinedLength;
  if(combined){
    const length=combined.fields.map(id=>String(object[id]??'')).join('').length;
    if(length<combined.min||length>combined.max)return false;
  }
  return true;
};

const optionToken=(option:PromptOption)=>[`${option.id}${option.label}`,`${option.id} ${option.label}`,option.label];
const orderedOptionsPresent=(text:string,options:readonly PromptOption[])=>{let cursor=0;for(const option of options){let found=-1,end=0;for(const token of optionToken(option)){const index=text.indexOf(token,cursor);if(index>=0&&(found<0||index<found)){found=index;end=index+token.length;}}if(found<0)return false;cursor=end;}return options.length>0;};
const firstOptionIndex=(text:string,options:readonly PromptOption[])=>{let result=-1;for(const option of options){for(const token of optionToken(option)){const index=text.indexOf(token);if(index>=0&&(result<0||index<result))result=index;}}return result;};

/** Returns the user-facing prompt while leaving the source-backed question text unchanged. */
export function questionPrompt(question:Question):string {
  const text=question.text.trim();
  const options=questionOptions(question);
  if(question.id==='Q25'||text.includes('最常跳过的一步'))return '请从以下步骤中选出你最常跳过的一步，并说明原因';
  const marker=/(?:单选|多选)(?:\s*[+＋]\s*[^：:；;?？]*)?[：:]/g;
  let match:RegExpExecArray|null;
  while((match=marker.exec(text))!==null){
    if(orderedOptionsPresent(text.slice(match.index+match[0].length),options))return text.slice(0,match.index).trim();
  }
  const optionStart=firstOptionIndex(text,options);
  if(optionStart>0){
    const separator=Math.max(text.lastIndexOf('：',optionStart),text.lastIndexOf(':',optionStart));
    if(separator>=0&&orderedOptionsPresent(text.slice(separator+1),options))return text.slice(0,separator).trim();
  }
  return text;
}

export function questionHint(question:Question):string {
  if(question.id==='Q25'||question.text.includes('20字以内'))return '单选 · 原因限 20 字';
  if(question.id==='Q38'||question.text.includes('补充原因'))return '单选 · 请补充原因';
  if(question.id==='Q39'||question.text.includes('文字或语音二选一'))return '文字或语音，可跳过';
  if(question.type==='multiple')return '可多选';
  if(question.type==='compound')return '按提示填写';
  return '选择最符合你真实情况的选项';
}

type OptionCardsProps={name:string;type:'single'|'multiple';options:readonly PromptOption[];value:AnswerValue|undefined;maximum?:number;compact?:boolean;disabled?:boolean;ariaLabelledBy?:string;onChange:(value:AnswerValue)=>void;onSingleSelect?:()=>void};
function OptionCards({name,type,options,value,maximum=options.length,compact=false,disabled=false,ariaLabelledBy,onChange,onSingleSelect}:OptionCardsProps){
  const [animatingOption,setAnimatingOption]=useState<string|null>(null);
  const animationTimer=useRef<ReturnType<typeof setTimeout>|null>(null);
  useEffect(()=>()=>{if(animationTimer.current!==null)clearTimeout(animationTimer.current);},[]);
  const selected=Array.isArray(value)?value:[];
  const animate=(id:string)=>{setAnimatingOption(id);if(animationTimer.current!==null)clearTimeout(animationTimer.current);animationTimer.current=setTimeout(()=>{animationTimer.current=null;setAnimatingOption(null);},OPTION_ANIMATION_MS);};
  const selectSingle=(id:string)=>{onChange(id);animate(id);onSingleSelect?.();};
  const toggleMultiple=(id:string)=>{onChange(selected.includes(id)?selected.filter(x=>x!==id):[...selected,id]);animate(id);};
  return <fieldset className={`assessment-options${compact?' assessment-options-compact':''}`} aria-labelledby={ariaLabelledBy} disabled={disabled}>{options.map((option,index)=>{const isSelected=type==='single'?value===option.id:selected.includes(option.id);return <label className={`assessment-option-card${isSelected?' selected':''}${animatingOption===option.id?' selection-animating':''}`} key={option.id}><input aria-label={option.label} type={type==='single'?'radio':'checkbox'} name={name} checked={isSelected} disabled={disabled||(type==='multiple'&&!isSelected&&selected.length>=maximum)} onChange={()=>type==='single'?selectSingle(option.id):toggleMultiple(option.id)}/><span className="option-card-key">{String.fromCharCode(65+index)}</span><span className="option-card-label">{option.label}</span><span className="option-card-check" aria-hidden="true">✓</span></label>;})}</fieldset>;
}

export function QuestionInput({question,value,onChange,onSingleSelect,disabled=false,ariaLabelledBy}:{question:Question;value:AnswerValue|undefined;onChange:(value:AnswerValue)=>void;onSingleSelect?:()=>void;disabled?:boolean;ariaLabelledBy?:string}) {
  if(question.type==='compound') { const objectValue=(value&&typeof value==='object'&&!Array.isArray(value)?value:{}) as Record<string,string|string[]|number>; const setField=(id:string,next:string|string[]|number)=>{const updated={...objectValue,[id]:next};for(const field of question.fields??[])if(field.condition&&field.condition.field===id&&next!==field.condition.equals)delete updated[field.id];onChange(updated);};return <fieldset className="assessment-compound" disabled={disabled}><legend className="sr-only">{questionPrompt(question)}</legend>{question.fields?.map(field=>{const active=!field.condition||objectValue[field.condition.field]===field.condition.equals;if(!active)return null;const label=fieldLabels[field.id]??field.id,labelId=`${question.id}-${field.id}-label`;return <div className="assessment-field" key={field.id}><span className="assessment-field-label" id={labelId}>{label}</span>{field.type==='single'||field.type==='multiple'?<OptionCards compact ariaLabelledBy={labelId} name={`${question.id}-${field.id}`} type={field.type} options={field.options??[]} value={objectValue[field.id]} maximum={field.maxSelections??field.options?.length??0} disabled={disabled} onChange={next=>{if(typeof next==='object'&&!Array.isArray(next))return;setField(field.id,next)}}/>:field.type==='integer'?<input aria-labelledby={labelId} type="number" min={field.min} max={field.max} value={(objectValue[field.id] as number|undefined)??''} onChange={e=>{if(e.target.value===''){const updated={...objectValue};delete updated[field.id];onChange(updated);}else setField(field.id,Number(e.target.value));}}/>:field.type==='audio'?<p>{label}（语音输入待实现）</p>:<textarea aria-labelledby={labelId} maxLength={field.maxLength} value={(objectValue[field.id] as string|undefined)??''} onChange={e=>setField(field.id,e.target.value)}/>}</div>;})}</fieldset>; }
  if(question.type==='scale') return <input aria-label={questionPrompt(question)} aria-describedby={ariaLabelledBy} disabled={disabled} type="range" min={question.min} max={question.max} value={(value as number|undefined)??question.min} onChange={e=>onChange(Number(e.target.value))}/>;
  if(question.type==='experience') return <textarea aria-label={questionPrompt(question)} aria-describedby={ariaLabelledBy} disabled={disabled} maxLength={question.maxLength} value={(value as string)??''} onChange={e=>onChange(e.target.value)}/>;
  const options=questionOptions(question),maximum=question.fields?.[0]?.maxSelections??question.maxSelections??options.length;
  return <OptionCards ariaLabelledBy={ariaLabelledBy} name={question.id} type={question.type} options={options} value={value} maximum={maximum} disabled={disabled} onChange={onChange} onSingleSelect={question.type==='single'?onSingleSelect:undefined}/>;
}
export const SubmittedNotice=({jobId}:{jobId:string})=><section><h2>已进入生成队列</h2><p>任务编号：{jobId}</p></section>;
const emit=(sessionId:string,eventType:string,metadata:Record<string,string>={})=>{void sendEvent(sessionId,eventType,metadata).catch(()=>undefined);};
const readDraft=(raw:string|null,fallback:DraftState):DraftState=>{if(!raw)return fallback;try{const value=JSON.parse(raw) as DraftState;return value&&typeof value.revision==='number'&&value.answers&&value.dirty?value:fallback;}catch{return fallback;}};
const equalAnswer=(left:AnswerValue|undefined,right:AnswerValue|undefined)=>JSON.stringify(left)===JSON.stringify(right);

export function AssessmentFlow(){
  const [session,setSession]=useState<Session|null>(null),[owner,setOwner]=useState(''),[draft,setDraft]=useState<DraftState>({revision:0,answers:{},dirty:{}}),[index,setIndex]=useState(0),[job,setJob]=useState<string|null>(null),[error,setError]=useState(''),[submitting,setSubmitting]=useState(false);
  const current=useRef(draft), chain=useRef(Promise.resolve()), indexRef=useRef(0), autoAdvanceTimer=useRef<ReturnType<typeof setTimeout>|null>(null), headingRef=useRef<HTMLHeadingElement|null>(null), focusedQuestionRef=useRef<string|null>(null), submittingRef=useRef(false), submitKey=useRef(sessionStorage.getItem('assessment:submit-key')||crypto.randomUUID());
  sessionStorage.setItem('assessment:submit-key',submitKey.current);
  indexRef.current=index;
  useEffect(()=>()=>{if(autoAdvanceTimer.current!==null)clearTimeout(autoAdvanceTimer.current);},[]);
  useEffect(()=>{
    const currentQuestion=session?.questions[index];
    if(!currentQuestion)return;
    if(focusedQuestionRef.current!==null&&focusedQuestionRef.current!==currentQuestion.id)headingRef.current?.focus();
    focusedQuestionRef.current=currentQuestion.id;
  },[session,index]);
  const persist=(next:DraftState,id?:string)=>{current.current=next;setDraft(next);if(id&&owner)localStorage.setItem(cacheKey(owner,id),JSON.stringify(next));};
  useEffect(()=>{ensureIdentity().then(identity=>{setOwner(identity.ownerId);return getCurrent().then(x=>x.session??createSession()).then(s=>({identity,s}));}).then(({identity,s})=>{setSession(s);setJob(s.jobId??null);const cached=readDraft(localStorage.getItem(cacheKey(identity.ownerId,s.id)),{revision:s.revision,answers:{},dirty:{}});const merged=mergeServerDraft(cached,s);current.current=merged;setDraft(merged);emit(s.id,'assessment_start',{status:s.status});}).catch(()=>setError('暂时无法载入，答案缓存仍会保留。'));},[]);
  useEffect(()=>{if(!session||!session.questions.length)return;emit(session.id,'question_view',{questionId:session.questions[0].id});return()=>emit(session.id,'assessment_exit',{status:session.status});},[session]);
  if(job)return <SubmittedNotice jobId={job}/>; if(!session)return <main><p>{error||'正在载入测评…'}</p></main>;
  if(!session.questions.length)return <main><p>{error||'正在载入测评…'}</p></main>;
  const question=session.questions[index],lastIndex=session.questions.length-1;
  const save=(qid:string)=>{chain.current=chain.current.then(async()=>{const before=current.current;if(!before.dirty[qid]||Object.prototype.hasOwnProperty.call(before.conflicts??{},qid))return;try{let sentValue=before.answers[qid],result;try{result=await saveAnswer(session.id,qid,sentValue,before.revision);}catch(error){if(!(error instanceof ApiError)||error.status!==409)throw error;const server=await getSession(session.id),latest=current.current,merged=mergeServerDraft(latest,server);if(equalAnswer(server.answers.find(answer=>answer.questionId===qid)?.value,latest.answers[qid])){persist({...merged,dirty:{...merged.dirty,[qid]:false}},session.id);setError('');return;}persist(merged,session.id);if(Object.prototype.hasOwnProperty.call(merged.conflicts??{},qid)){setError('另一处已修改此答案，请选择保留版本。');return;}sentValue=merged.answers[qid];result=await saveAnswer(session.id,qid,sentValue,server.revision);}const latest=current.current;persist({...latest,revision:result.revision,dirty:{...latest.dirty,[qid]:!equalAnswer(latest.answers[qid],sentValue)},baseAnswers:{...latest.baseAnswers,[qid]:sentValue}},session.id);emit(session.id,'assessment_save',{questionId:qid,status:'saved'});setError('');}catch{setError('保存失败，可重试；本机答案未清空。');}});};
  const cancelAutoAdvance=()=>{if(autoAdvanceTimer.current!==null){clearTimeout(autoAdvanceTimer.current);autoAdvanceTimer.current=null;}};
  const move=(to:number)=>{cancelAutoAdvance();if(submittingRef.current||to<0||to>lastIndex)return;const from=indexRef.current;indexRef.current=to;emit(session.id,to<from?'question_back':'question_view',{questionId:session.questions[to].id});setIndex(to);};
  const scheduleAutoAdvance=()=>{if(submittingRef.current||question.type!=='single'||index>=lastIndex)return;const fromIndex=index,questionId=question.id;cancelAutoAdvance();autoAdvanceTimer.current=setTimeout(()=>{autoAdvanceTimer.current=null;if(submittingRef.current||indexRef.current!==fromIndex||!questionComplete(question,current.current.answers[questionId]))return;const nextIndex=fromIndex+1;indexRef.current=nextIndex;emit(session.id,'question_view',{questionId:session.questions[nextIndex].id});setIndex(nextIndex);},OPTION_ANIMATION_MS);};
  const change=(value:AnswerValue)=>{if(submittingRef.current)return;persist(updateAnswer(current.current,question.id,value),session.id);emit(session.id,'question_answer',{questionId:question.id});save(question.id);};
  const retry=()=>{if(submittingRef.current)return;for(const qid of Object.keys(current.current.dirty))if(current.current.dirty[qid])save(qid);};
  const conflictEntry=Object.entries(draft.conflicts??{})[0];
  const keepLocal=()=>{if(submittingRef.current||!conflictEntry)return;const [qid]=conflictEntry,next={...current.current,conflicts:{...current.current.conflicts}};delete next.conflicts![qid];persist(next,session.id);setError('');save(qid);};
  const useServer=()=>{if(submittingRef.current||!conflictEntry)return;const [qid,serverValue]=conflictEntry,next={...current.current,answers:{...current.current.answers},dirty:{...current.current.dirty,[qid]:false},conflicts:{...current.current.conflicts}};delete next.conflicts![qid];if(serverValue===undefined)delete next.answers[qid];else next.answers[qid]=serverValue;persist(next,session.id);setError('');};
  const complete=session.questions.every(q=>questionComplete(q,draft.answers[q.id]));
  const submit=()=>{if(submittingRef.current)return;submittingRef.current=true;setSubmitting(true);cancelAutoAdvance();chain.current.then(()=>{if(Object.values(current.current.dirty).some(Boolean)||Object.keys(current.current.conflicts??{}).length)throw new Error('unsaved');return submitSession(session.id,submitKey.current);}).then(x=>{cancelAutoAdvance();emit(session.id,'assessment_submit',{status:'queued'});setJob(x.jobId);}).catch(()=>{submittingRef.current=false;setSubmitting(false);setError(Object.keys(current.current.conflicts??{}).length?'请先处理答案冲突。':Object.values(current.current.dirty).some(Boolean)?'仍有答案未保存，请先重试保存。':'提交失败，请重试；答案不会清空。');});};
  const hasUnsaved=Object.values(draft.dirty).some(Boolean);
  const answeredCount=Object.keys(draft.answers).length, progress=Math.round(answeredCount/session.questions.length*100);
  return <main className="assessment-page">{session.demo&&<aside className="assessment-demo-notice">演示数据：内容未经专家确认，仅用于流程展示。</aside>}<header className="assessment-header"><div className="assessment-brand"><span className="brand-dot"/>Talent Map</div><span className="assessment-step">职业倾向测评 <b>{index+1}</b> / {session.questions.length}</span><span className="assessment-save-state" role="status" aria-live="polite">{hasUnsaved?'正在保存…':'已自动保存'}</span></header><div className="assessment-progress" role="progressbar" aria-label="答题进度" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress} aria-valuetext={`${answeredCount} / ${session.questions.length}`}><span style={{width:`${progress}%`}}/></div><section className="assessment-container"><div className="assessment-kicker">QUESTION {String(index+1).padStart(2,'0')}</div><div className="assessment-heading"><h1 id={`question-heading-${question.id}`} ref={headingRef} tabIndex={-1}>{index+1}. {questionPrompt(question)}</h1><p>{questionHint(question)}</p></div><QuestionInput key={question.id} question={question} value={draft.answers[question.id]} onChange={change} onSingleSelect={scheduleAutoAdvance} disabled={submitting} ariaLabelledBy={`question-heading-${question.id}`}/>{error&&<p role="alert" className="assessment-error">{error}</p>}{conflictEntry?<div className="assessment-conflict"><button disabled={submitting} onClick={keepLocal}>保留本机答案</button><button disabled={submitting} onClick={useServer}>使用另一处答案</button></div>:hasUnsaved&&<button className="assessment-retry" disabled={submitting} onClick={retry}>重试保存</button>}</section><footer className="assessment-footer"><div className="assessment-footer-inner"><span className="assessment-count">已完成 <b>{answeredCount}</b> / {session.questions.length}</span><nav><button className="assessment-nav secondary" disabled={submitting||index===0} onClick={()=>move(index-1)}>上一题</button><button aria-label="下一题" className="assessment-nav primary" disabled={submitting||index===lastIndex} onClick={()=>move(index+1)}>下一题 <span aria-hidden="true">→</span></button></nav><button className="assessment-submit" disabled={submitting||!complete} onClick={submit}>提交并进入生成队列</button></div></footer></main>;
}
