// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import official from '../../../../backend/seed/official-questionnaire.json';
import { AssessmentFlow } from './AssessmentFlow';
import type { Question } from './api';

const questions=official.questions as unknown as Question[];
const reply=(body:unknown,status=200)=>Promise.resolve(new Response(status===204?null:JSON.stringify(body),{status}));

function mockSession(initialAnswers:{questionId:string;value:unknown}[]=[]){
  const saved:unknown[]=[];
  vi.spyOn(globalThis,'fetch').mockImplementation((url,init)=>{
    const path=String(url);
    if(path.endsWith('/identity/anonymous'))return reply({ownerId:'owner',csrfToken:'csrf'},201);
    if(path.includes('/sessions/current'))return reply({session:{id:'s',revision:initialAnswers.length,status:'draft',questions,answers:initialAnswers,demo:false}});
    if(path.includes('/answers/')){saved.push(JSON.parse(String(init?.body)).value);return reply({revision:initialAnswers.length+saved.length,answeredCount:1});}
    return reply({},204);
  });
  return saved;
}

async function goTo(number:number){await screen.findByRole('button',{name:'下一题'});for(let i=1;i<number;i++)fireEvent.click(screen.getByRole('button',{name:'下一题'}));await screen.findByText(new RegExp(`^${number}\\.`));}

describe('official compound assessment',()=>{
  beforeEach(()=>{localStorage.clear();sessionStorage.clear();Object.defineProperty(globalThis,'crypto',{value:{randomUUID:()=>`event-${Math.random()}`},configurable:true});});
  afterEach(()=>{cleanup();vi.restoreAllMocks();});

  it('saves partial Q25 fields and restores them after remount',async()=>{
    const saved=mockSession();render(<AssessmentFlow/>);await goTo(25);
    fireEvent.click(screen.getByLabelText('定义问题'));
    await waitFor(()=>expect(saved).toEqual([{choice:'A'}]));
    fireEvent.change(screen.getByLabelText('原因'),{target:{value:'经常跳过'}});
    await waitFor(()=>expect(saved).toHaveLength(2));
    cleanup();vi.restoreAllMocks();
    mockSession([{questionId:'Q25',value:{choice:'A',reason:'经常跳过'}}]);render(<AssessmentFlow/>);await goTo(25);
    expect((screen.getByLabelText('原因') as HTMLTextAreaElement).value).toBe('经常跳过');
    expect((screen.getByLabelText('定义问题') as HTMLInputElement).checked).toBe(true);
  });

  it('uses actual Q36 and Q37 conditions',async()=>{
    mockSession();render(<AssessmentFlow/>);await goTo(36);
    expect(screen.queryByLabelText('原因')).toBeNull();
    fireEvent.click(screen.getByLabelText('视任务而定并说明条件'));
    expect(screen.getByLabelText('原因')).toBeTruthy();
    fireEvent.click(screen.getByRole('button',{name:'下一题'}));
    fireEvent.click(screen.getByLabelText('暂无相关经历'));
    expect(screen.queryByLabelText('目标')).toBeNull();
    expect(screen.queryByLabelText('你的动作')).toBeNull();
  });

  it('shows actual optional Q39 text and pending audio',async()=>{
    mockSession();render(<AssessmentFlow/>);await goTo(39);
    expect(screen.getByText(/语音输入待实现/)).toBeTruthy();
    expect(screen.getByLabelText('文字说明')).toBeTruthy();
  });
});
