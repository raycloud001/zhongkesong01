export type AnswerValue = string | string[] | number | Record<string, string | string[] | number>;
export type DraftState = { revision: number; answers: Record<string, AnswerValue>; dirty: Record<string, boolean>; baseAnswers?: Record<string, AnswerValue>; conflicts?: Record<string, AnswerValue | undefined> };
export const cacheKey = (ownerId: string, sessionId: string) => `assessment:${ownerId}:${sessionId}`;
export function updateAnswer(state: DraftState, questionId: string, value: AnswerValue): DraftState {
  return { ...state, answers: { ...state.answers, [questionId]: value }, dirty: { ...state.dirty, [questionId]: true } };
}
export function mergeServerDraft(local: DraftState, server: { revision: number; answers: { questionId: string; value: AnswerValue }[] }): DraftState {
  if (server.revision < local.revision) return local;
  const serverAnswers = Object.fromEntries(server.answers.map(answer => [answer.questionId, answer.value]));
  const answers = { ...serverAnswers }, conflicts = { ...local.conflicts };
  for (const [id, dirty] of Object.entries(local.dirty)) if (dirty) {
    answers[id] = local.answers[id];
    if (JSON.stringify(local.answers[id]) === JSON.stringify(serverAnswers[id])) delete conflicts[id];
    else if (server.revision > local.revision && (!local.baseAnswers || JSON.stringify(local.baseAnswers[id]) !== JSON.stringify(serverAnswers[id]))) conflicts[id] = serverAnswers[id];
  }
  return { revision: server.revision, answers, dirty: { ...local.dirty }, baseAnswers: serverAnswers, conflicts };
}
