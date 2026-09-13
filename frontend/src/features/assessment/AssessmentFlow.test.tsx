import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { QuestionInput, SubmittedNotice, questionComplete, questionPrompt } from './AssessmentFlow';

describe('assessment question rendering', () => {
  it.each([
    [{ id: 'q1', type: 'scale', text: '量表', required: true, min: 1, max: 5 }, 'type="range"'],
    [{ id: 'q2', type: 'single', text: '单选', required: true, options: [{ id: 'a', label: 'A' }] }, 'type="radio"'],
    [{ id: 'q3', type: 'multiple', text: '多选', required: true, options: [{ id: 'a', label: 'A' }], minSelections: 1, maxSelections: 1 }, 'type="checkbox"'],
    [{ id: 'q4', type: 'experience', text: '经历', required: false, maxLength: 500 }, '<textarea'],
  ] as const)('renders every supported type', (question, marker) => {
    expect(renderToStaticMarkup(<QuestionInput question={question} value={undefined} onChange={() => {}} />)).toContain(marker);
  });

  it('renders answer choices as accessible option cards', () => {
    const html = renderToStaticMarkup(<QuestionInput question={{ id: 'q1', type: 'single', text: '单选', required: true, options: [{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }] }} value={undefined} onChange={() => {}} />);
    expect(html).toContain('assessment-option-card');
    expect(html).toContain('option-card-label');
  });

  it('renders and validates choices supplied only on the choice field', () => {
    const question:import('./api').Question={id:'field-only',type:'single',text:'单选',required:true,fields:[{id:'choice',type:'single',required:true,options:[{id:'a',label:'A'},{id:'b',label:'B'}]}]};
    const html=renderToStaticMarkup(<QuestionInput question={question} value={undefined} onChange={() => {}} />);
    expect(html).toContain('option-card-label');
    expect(html).toContain('>A</span>');
    expect(questionComplete(question,'a')).toBe(true);
    expect(questionComplete(question,'unknown')).toBe(false);
  });

  it.each([
    [
      { id: 'q1', type: 'single', text: '哪类任务最容易让你进入状态？单选：A深入研究；B创作表达', required: true, options: [{ id: 'A', label: '深入研究' }, { id: 'B', label: '创作表达' }] },
      '哪类任务最容易让你进入状态？',
    ],
    [
      { id: 'Q36', type: 'compound', text: '两个描述中选更像你的一个：A先快速产出再迭代；B先充分研究再产出；C视任务而定并说明条件', required: true, fields: [{ id: 'choice', type: 'single', required: true, options: [{ id: 'A', label: '先快速产出再迭代' }, { id: 'B', label: '先充分研究再产出' }, { id: 'C', label: '视任务而定并说明条件' }] }] },
      '两个描述中选更像你的一个',
    ],
    [
      { id: 'Q38', type: 'compound', text: '目标岗位校准题：你当前最想验证哪个岗位任务？单选+补充原因：内容生产/用户增长/需求分析', required: true, fields: [{ id: 'target', type: 'single', required: true, options: [{ id: 'T1', label: '内容生产' }, { id: 'T2', label: '用户增长' }, { id: 'T3', label: '需求分析' }] }] },
      '目标岗位校准题：你当前最想验证哪个岗位任务？',
    ],
  ] as const)('keeps repeated options out of the question prompt', (question, expected) => {
    expect(questionPrompt(question)).toBe(expected);
  });

  it('labels submission as queued without claiming a report exists', () => {
    const html = renderToStaticMarkup(<SubmittedNotice jobId="job-1" />);
    expect(html).toContain('已进入生成队列');
    expect(html).not.toContain('报告已生成');
  });

  it('trims required compound text and applies the Q37 combined bounds', () => {
    const question:import('./api').Question={id:'Q37',type:'compound',text:'经历',required:true,fields:[
      {id:'status',type:'single',required:true,options:[{id:'has_experience',label:'有'}]},
      {id:'goal',type:'text',required:true,condition:{field:'status',equals:'has_experience'},combinedLength:{fields:['goal','action','result'],min:100,max:200}},
      {id:'action',type:'text',required:true,condition:{field:'status',equals:'has_experience'}},
      {id:'result',type:'text',condition:{field:'status',equals:'has_experience'}},
    ]};
    expect(questionComplete(question,{status:'has_experience',goal:' '.repeat(50),action:'甲'.repeat(50)})).toBe(false);
    expect(questionComplete(question,{status:'has_experience',goal:'甲'.repeat(50),action:'乙'.repeat(50)})).toBe(true);
    expect(questionComplete(question,{status:'has_experience',goal:'甲'.repeat(101),action:'乙'.repeat(100)})).toBe(false);
  });

  it('validates required multiple answers against selection bounds and option ids', () => {
    const question:import('./api').Question={id:'Q04',type:'multiple',text:'多选',required:true,minSelections:2,maxSelections:2,options:[{id:'A',label:'甲'},{id:'B',label:'乙'},{id:'C',label:'丙'}]};
    expect(questionComplete(question,['A'])).toBe(false);
    expect(questionComplete(question,['A','B'])).toBe(true);
    expect(questionComplete(question,['A','A'])).toBe(false);
    expect(questionComplete(question,['A','C','B'])).toBe(false);
    expect(questionComplete(question,['A','X'])).toBe(false);
  });
});
