import { describe, expect, it } from 'vitest';

import { cacheKey, mergeServerDraft, updateAnswer } from './state';

describe('assessment draft state', () => {
  it('keys cached drafts by owner and session', () => {
    expect(cacheKey('owner-a', 'session-1')).toBe('assessment:owner-a:session-1');
  });

  it('restores server answers and preserves a newer unsaved local edit', () => {
    const local = updateAnswer({ revision: 3, answers: { q1: 2 }, dirty: {} }, 'q1', 5);
    const merged = mergeServerDraft(local, { revision: 3, answers: [{ questionId: 'q1', value: 2 }] });
    expect(merged.answers.q1).toBe(5);
    expect(merged.dirty.q1).toBe(true);
  });

  it('accepts a newer server revision after a retry', () => {
    const merged = mergeServerDraft(
      { revision: 2, answers: { q1: 2 }, dirty: {} },
      { revision: 3, answers: [{ questionId: 'q1', value: 4 }] },
    );
    expect(merged).toEqual({ revision: 3, answers: { q1: 4 }, dirty: {}, baseAnswers: { q1: 4 }, conflicts: {} });
  });

  it('marks a persisted conflict when a dirty local answer differs from the server', () => {
    const merged = mergeServerDraft(
      { revision: 2, answers: { q1: 5 }, dirty: { q1: true }, baseAnswers: { q1: 2 } },
      { revision: 3, answers: [{ questionId: 'q1', value: 4 }] },
    );
    expect(merged.answers.q1).toBe(5);
    expect(merged.conflicts).toEqual({ q1: 4 });
  });

  it('treats an old dirty cache without a baseline conservatively as a conflict', () => {
    const merged = mergeServerDraft(
      { revision: 2, answers: { q1: 5 }, dirty: { q1: true } },
      { revision: 3, answers: [{ questionId: 'q1', value: 4 }] },
    );
    expect(merged.conflicts).toEqual({ q1: 4 });
  });
});
