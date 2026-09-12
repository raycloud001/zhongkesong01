// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AssessmentFlow } from './AssessmentFlow';

const questions = Array.from({length:40},(_,i)=>({id:`q${i+1}`,type:'scale' as const,text:`题${i+1}`,required:i!==39,min:1,max:5}));
const response=(body:unknown,status=200)=>Promise.resolve(new Response(status === 204 ? null : JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}}));

describe('AssessmentFlow lifecycle',()=>{
  beforeEach(()=>{localStorage.clear();sessionStorage.clear();Object.defineProperty(globalThis,'crypto',{value:{randomUUID:vi.fn(()=>`id-${Math.random()}`)},configurable:true});});
  afterEach(()=>{ cleanup(); vi.restoreAllMocks(); });

  it('bootstraps identity and initializes a newly created empty session',async()=>{
    const fetchMock=vi.spyOn(globalThis,'fetch').mockImplementation((url,init)=>{
      const path=String(url);
      if(path.endsWith('/identity/anonymous'))return response({ownerId:'owner-1',csrfToken:'csrf'},201);
      if(path.includes('/sessions/current'))return response({session:null});
      if(path.endsWith('/sessions'))return response({id:'s1',revision:0,status:'draft',questions,answers:[],demo:true,jobId:null},201);
      return response({},204);
    });
    render(<AssessmentFlow/>);
    expect(await screen.findByText('1. 题1')).toBeTruthy();
    expect(fetchMock.mock.calls.some(([url])=>String(url).endsWith('/identity/anonymous'))).toBe(true);
  });

  it('restores local unsaved data and serializes quick saves without losing the latest edit',async()=>{
    localStorage.setItem('assessment:owner-1:s1',JSON.stringify({revision:2,answers:{q1:5},dirty:{q1:true}}));
    let resolveFirst:(value:Response)=>void=()=>{};
    const firstSave=new Promise<Response>(resolve=>{resolveFirst=resolve;});
    const fetchMock=vi.spyOn(globalThis,'fetch').mockImplementation((url,init)=>{
      const path=String(url);
      if(path.endsWith('/identity/anonymous'))return response({ownerId:'owner-1',csrfToken:'csrf'});
      if(path.includes('/sessions/current'))return response({session:{id:'s1',revision:2,status:'draft',questions,answers:[{questionId:'q1',value:2}],demo:true}});
      if(path.includes('/answers/'))return fetchMock.mock.calls.filter(([u])=>String(u).includes('/answers/')).length===1?firstSave:response({revision:4,answeredCount:1});
      return response({},204);
    });
    render(<AssessmentFlow/>);
    const slider=await screen.findByLabelText('题1') as HTMLInputElement;
    expect(slider.value).toBe('5');
    fireEvent.change(slider,{target:{value:'3'}});
    await waitFor(()=>expect(fetchMock.mock.calls.filter(([u])=>String(u).includes('/answers/')).length).toBe(1));
    fireEvent.change(slider,{target:{value:'4'}});
    resolveFirst(new Response(JSON.stringify({revision:3,answeredCount:1}),{status:200,headers:{'Content-Type':'application/json'}}));
    await waitFor(()=>expect(fetchMock.mock.calls.filter(([u])=>String(u).includes('/answers/')).length).toBe(2));
    expect((screen.getByLabelText('题1') as HTMLInputElement).value).toBe('4');
  });

  it('restores submitted queue state on refresh',async()=>{
    vi.spyOn(globalThis,'fetch').mockImplementation((url)=>String(url).endsWith('/identity/anonymous')?response({ownerId:'owner-1',csrfToken:'csrf'}):String(url).includes('/sessions/current')?response({session:{id:'s1',revision:39,status:'submitted',questions,answers:[],demo:false,jobId:'job-1'}}):response({},204));
    render(<AssessmentFlow/>);
    expect(await screen.findByText('已进入生成队列')).toBeTruthy();
    expect(screen.getByText('任务编号：job-1')).toBeTruthy();
  });

  it('retains an offline edit across remount and retries it', async () => {
    let saves = 0;
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((url) => {
      const path = String(url);
      if (path.endsWith('/identity/anonymous')) return response({ownerId:'owner-1',csrfToken:'csrf'});
      if (path.includes('/sessions/current')) return response({session:{id:'s1',revision:0,status:'draft',questions,answers:[],demo:true}});
      if (path.includes('/answers/')) {
        saves += 1;
        return saves === 1 ? Promise.reject(new Error('offline')) : response({revision:1,answeredCount:1});
      }
      return response({},204);
    });
    const first = render(<AssessmentFlow/>);
    fireEvent.change(await screen.findByLabelText('题1'), {target:{value:'5'}});
    expect((await screen.findByRole('alert')).textContent).toContain('保存失败');
    first.unmount();
    render(<AssessmentFlow/>);
    expect((await screen.findByLabelText('题1') as HTMLInputElement).value).toBe('5');
    fireEvent.click(screen.getByRole('button',{name:'重试保存'}));
    await waitFor(() => expect(saves).toBe(2));
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
    expect(fetchMock).toHaveBeenCalled();
  });

  it('allows submission when only the optional final question is omitted and reuses the retry key', async () => {
    const requiredAnswers = questions.slice(0,39).map(question => ({questionId:question.id,value:3}));
    const submitKeys:string[] = [];
    const eventTypes:string[] = [];
    let attempts = 0;
    vi.spyOn(globalThis,'fetch').mockImplementation((url,init)=>{
      const path=String(url);
      if(path.endsWith('/identity/anonymous'))return response({ownerId:'owner-1',csrfToken:'csrf'});
      if(path.includes('/sessions/current'))return response({session:{id:'s1',revision:39,status:'draft',questions,answers:requiredAnswers,demo:false}});
      if(path.endsWith('/submit')) {
        submitKeys.push(new Headers(init?.headers).get('Idempotency-Key') ?? '');
        attempts += 1;
        return attempts === 1 ? Promise.reject(new Error('lost response')) : response({jobId:'job-1'});
      }
      if(path.endsWith('/events')) { eventTypes.push(JSON.parse(String(init?.body)).eventType); return response({},204); }
      return response({},204);
    });
    render(<AssessmentFlow/>);
    const submit = await screen.findByRole('button',{name:'提交并进入生成队列'});
    expect((submit as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(submit);
    expect((await screen.findByRole('alert')).textContent).toContain('提交失败');
    fireEvent.click(submit);
    expect(await screen.findByText('任务编号：job-1')).toBeTruthy();
    expect(submitKeys).toHaveLength(2);
    expect(submitKeys[0]).toBe(submitKeys[1]);
    expect(eventTypes).toContain('assessment_submit');
  });

  it('does not submit while a locally restored answer is still unsaved', async () => {
    const answers=Object.fromEntries(questions.slice(0,39).map(question=>[question.id,3]));
    localStorage.setItem('assessment:owner-1:s1',JSON.stringify({revision:39,answers,dirty:{q1:true}}));
    let submissions=0;
    vi.spyOn(globalThis,'fetch').mockImplementation((url)=>{
      const path=String(url);
      if(path.endsWith('/identity/anonymous'))return response({ownerId:'owner-1',csrfToken:'csrf'});
      if(path.includes('/sessions/current'))return response({session:{id:'s1',revision:39,status:'draft',questions,answers:questions.slice(0,39).map(question=>({questionId:question.id,value:3})),demo:false}});
      if(path.endsWith('/submit')) { submissions+=1; return response({jobId:'job-1'}); }
      return response({},204);
    });
    render(<AssessmentFlow/>);
    fireEvent.click(await screen.findByRole('button',{name:'提交并进入生成队列'}));
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(submissions).toBe(0);
  });

  it('reconciles a lost successful save response without overwriting the same answer again', async () => {
    let detailCalls=0;
    let saveCalls=0;
    vi.spyOn(globalThis,'fetch').mockImplementation((url)=>{
      const path=String(url);
      if(path.endsWith('/identity/anonymous'))return response({ownerId:'owner-1',csrfToken:'csrf'});
      if(path.includes('/sessions/current'))return response({session:{id:'s1',revision:0,status:'draft',questions,answers:[],demo:false}});
      if(path.endsWith('/sessions/s1')) { detailCalls+=1; return response({id:'s1',revision:1,status:'draft',questions,answers:[{questionId:'q1',value:5}],demo:false}); }
      if(path.includes('/answers/')) { saveCalls+=1; return response({error:{code:'REVISION_CONFLICT'}},409); }
      return response({},204);
    });
    render(<AssessmentFlow/>);
    fireEvent.change(await screen.findByLabelText('题1'),{target:{value:'5'}});
    await waitFor(()=>expect(detailCalls).toBe(1));
    await waitFor(()=>expect(screen.queryByRole('button',{name:'重试保存'})).toBeNull());
    expect(saveCalls).toBe(1);
  });

  it('asks before overwriting a conflicting answer and keeps the chosen local value', async () => {
    let detailCalls=0;
    const savedBodies:Record<string,unknown>[]=[];
    vi.spyOn(globalThis,'fetch').mockImplementation((url,init)=>{
      const path=String(url);
      if(path.endsWith('/identity/anonymous'))return response({ownerId:'owner-1',csrfToken:'csrf'});
      if(path.includes('/sessions/current'))return response({session:{id:'s1',revision:0,status:'draft',questions,answers:[],demo:false}});
      if(path.endsWith('/sessions/s1')) { detailCalls+=1; return response({id:'s1',revision:1,status:'draft',questions,answers:[{questionId:'q1',value:2}],demo:false}); }
      if(path.includes('/answers/')) {
        const body=JSON.parse(String(init?.body)); savedBodies.push(body);
        return savedBodies.length===1?response({error:{code:'REVISION_CONFLICT'}},409):response({revision:2,answeredCount:2});
      }
      return response({},204);
    });
    render(<AssessmentFlow/>);
    fireEvent.change(await screen.findByLabelText('题1'),{target:{value:'5'}});
    const keepLocal=await screen.findByRole('button',{name:'保留本机答案'});
    expect(savedBodies).toEqual([{value:5,revision:0}]);
    fireEvent.click(keepLocal);
    await waitFor(()=>expect(savedBodies).toHaveLength(2));
    expect(savedBodies).toEqual([{value:5,revision:0},{value:5,revision:1}]);
    await waitFor(()=>expect(screen.queryByRole('button',{name:'重试保存'})).toBeNull());
    expect((screen.getByLabelText('题1') as HTMLInputElement).value).toBe('5');
  });

  it('retries every dirty cached answer in the serialized queue', async () => {
    localStorage.setItem('assessment:owner-1:s1',JSON.stringify({revision:2,answers:{q1:4,q2:5},dirty:{q1:true,q2:true}}));
    const saved:string[]=[];
    vi.spyOn(globalThis,'fetch').mockImplementation((url)=>{
      const path=String(url);
      if(path.endsWith('/identity/anonymous'))return response({ownerId:'owner-1',csrfToken:'csrf'});
      if(path.includes('/sessions/current'))return response({session:{id:'s1',revision:2,status:'draft',questions,answers:[],demo:false}});
      if(path.includes('/answers/')) { saved.push(path.split('/').slice(-1)[0] ?? ''); return response({revision:2+saved.length,answeredCount:saved.length}); }
      return response({},204);
    });
    render(<AssessmentFlow/>);
    fireEvent.click(await screen.findByRole('button',{name:'重试保存'}));
    await waitFor(()=>expect(saved).toEqual(['q1','q2']));
  });

  it('ignores a malformed cached draft and restores the server session', async () => {
    localStorage.setItem('assessment:owner-1:s1','not-json');
    vi.spyOn(globalThis,'fetch').mockImplementation((url)=>{
      const path=String(url);
      if(path.endsWith('/identity/anonymous'))return response({ownerId:'owner-1',csrfToken:'csrf'});
      if(path.includes('/sessions/current'))return response({session:{id:'s1',revision:1,status:'draft',questions,answers:[{questionId:'q1',value:4}],demo:false}});
      return response({},204);
    });
    render(<AssessmentFlow/>);
    expect((await screen.findByLabelText('题1') as HTMLInputElement).value).toBe('4');
  });

  it('emits lifecycle events with identifier/status metadata and no answer values', async () => {
    const eventBodies:Record<string,unknown>[]=[];
    vi.spyOn(globalThis,'fetch').mockImplementation((url,init)=>{
      const path=String(url);
      if(path.endsWith('/identity/anonymous'))return response({ownerId:'owner-1',csrfToken:'csrf'});
      if(path.includes('/sessions/current'))return response({session:{id:'s1',revision:0,status:'draft',questions,answers:[],demo:false}});
      if(path.includes('/answers/'))return response({revision:1,answeredCount:1});
      if(path.endsWith('/events')) { eventBodies.push(JSON.parse(String(init?.body))); return response({},204); }
      return response({},204);
    });
    const mounted=render(<AssessmentFlow/>);
    fireEvent.change(await screen.findByLabelText('题1'),{target:{value:'5'}});
    fireEvent.click(screen.getByRole('button',{name:'下一题'}));
    fireEvent.click(screen.getByRole('button',{name:'上一题'}));
    await waitFor(()=>expect(eventBodies.some(x=>x.eventType==='assessment_save')).toBe(true));
    mounted.unmount();
    await waitFor(()=>expect(eventBodies.some(x=>x.eventType==='assessment_exit')).toBe(true));
    expect(eventBodies.map(x=>x.eventType)).toEqual(expect.arrayContaining(['assessment_start','question_view','question_answer','question_back','assessment_save','assessment_exit']));
    for(const event of eventBodies) {
      expect(Object.keys(event.metadata as object).every(key=>key==='questionId'||key==='status')).toBe(true);
      expect(Object.values(event.metadata as object)).not.toContain(5);
    }
  });
});
