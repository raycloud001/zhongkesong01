import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { QuestionInput, SubmittedNotice, questionComplete } from './AssessmentFlow';

describe('assessment question rendering', () => {
  it.each([
    [{ id: 'q1', type: 'scale', text: '量表', required: true, min: 1, max: 5 }, 'type="range"'],
    [{ id: 'q2', type: 'single', text: '单选', required: true, options: [{ id: 'a', label: 'A' }] }, 'type="radio"'],
    [{ id: 'q3', type: 'multiple', text: '多选', required: true, options: [{ id: 'a', label: 'A' }], minSelections: 1, maxSelections: 1 }, 'type="checkbox"'],
    [{ id: 'q4', type: 'experience', text: '经历', required: false, maxLength: 500 }, '<textarea'],
  ] as const)('renders every supported type', (question, marker) => {
    expect(renderToStaticMarkup(<QuestionInput question={question} value={undefined} onChange={() => {}} />)).toContain(marker);
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
});
