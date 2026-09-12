import type { AnswerValue } from './state';
export type Field = { id:string; type:'single'|'multiple'|'scale'|'experience'|'text'|'integer'|'audio'; required?:boolean; requiredWhenCondition?:boolean; options?:readonly {id:string;label:string}[]; min?:number; max?:number; minSelections?:number; maxSelections?:number; maxLength?:number; condition?:{field:string;equals:string}; status?:string; combinedLength?:{fields:string[];min:number;max:number}; missingMeaning?:string };
export type Question = { id:string; type:'single'|'multiple'|'scale'|'experience'|'compound'; text:string; required:boolean; options?:readonly {id:string;label:string}[]; fields?:readonly Field[]; min?:number; max?:number; minSelections?:number; maxSelections?:number; maxLength?:number; dimension?:string };
export type Identity={ownerId:string;csrfToken:string};
export type Session = { id:string; revision:number; status:string; questions:Question[]; answers:{questionId:string;value:AnswerValue}[]; demo:boolean; jobId?:string|null };
const csrf = () => document.cookie.split('; ').find(x => x.startsWith('owner_csrf='))?.split('=')[1] ?? '';
export class ApiError extends Error { constructor(readonly status:number){super(`request failed: ${status}`);} }
async function request<T>(url:string, init:RequestInit={}):Promise<T>{ const response=await fetch(`/api/v1${url}`,{...init,headers:{'Content-Type':'application/json','X-CSRF-Token':csrf(),...init.headers}}); if(!response.ok) throw new ApiError(response.status); if(response.status===204)return undefined as T; return response.json(); }
export const getCurrent=()=>request<{session:Session|null}>('/sessions/current?mode=evidence_only');
export const getSession=(id:string)=>request<Session>(`/sessions/${id}`);
export async function ensureIdentity():Promise<Identity>{const response=await fetch('/api/v1/identity/anonymous',{method:'POST'});if(!response.ok)throw new Error('identity failed');return response.json();}
export const createSession=()=>request<Session>('/sessions',{method:'POST',body:JSON.stringify({mode:'evidence_only'})});
export const saveAnswer=(id:string,qid:string,value:AnswerValue,revision:number)=>request<{revision:number;answeredCount:number}>(`/sessions/${id}/answers/${qid}`,{method:'PUT',body:JSON.stringify({value,revision})});
export const submitSession=(id:string,key:string)=>request<{jobId:string}>(`/sessions/${id}/submit`,{method:'POST',headers:{'Idempotency-Key':key}});
export const sendEvent=(id:string,eventType:string,metadata:Record<string,string>={})=>request<void>(`/sessions/${id}/events`,{method:'POST',body:JSON.stringify({clientEventId:crypto.randomUUID(),eventType,metadata})});
