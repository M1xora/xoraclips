import { describe, expect, it } from 'vitest';
import { withNotice, type AnalyzeNotice } from './useAnalyze';

const CUT = 'Too many subtitle lines to analyse at once: only up to 34:26 was sent.';
const CAPPED = '10 clips of 3m do not fit: asking for at most 3.';

describe('withNotice', () => {
  it('keeps a warning the user has to act on', () => {
    expect(withNotice([], 'Transcript Limit', CUT)).toEqual([
      { stage: 'Transcript Limit', detail: CUT },
    ]);
  });

  it('ignores ordinary progress stages', () => {
    for (const stage of ['Context Assembly', 'Clip Verification & Alignment', '']) {
      expect(withNotice([], stage, 'working...')).toEqual([]);
    }
  });

  it('keeps every distinct warning, in the order they arrived', () => {
    const after = withNotice(withNotice([], 'Transcript Limit', CUT), 'Clip Count', CAPPED);
    expect(after.map((n) => n.stage)).toEqual(['Transcript Limit', 'Clip Count']);
  });

  it('does not repeat a stage when a retry resends it', () => {
    const once: AnalyzeNotice[] = withNotice([], 'Transcript Limit', CUT);
    const twice = withNotice(once, 'Transcript Limit', 'a differently worded repeat');
    // Same array back, so React skips the re-render too.
    expect(twice).toBe(once);
  });

  it('ignores a warning stage with no text to show', () => {
    expect(withNotice([], 'Transcript Limit', '')).toEqual([]);
  });

  it('keeps the numbers behind the sentence, so it can be said in any language', () => {
    const [notice] = withNotice([], 'Transcript Limit', CUT, {
      transcript_cut_at: 2066.1,
      transcript_unread_seconds: 717.9,
    });
    expect(notice.cutAt).toBe(2066.1);
    expect(notice.unreadSeconds).toBe(717.9);
  });

  it('leaves the numbers undefined when the event carries none', () => {
    const [notice] = withNotice([], 'Clip Count', CAPPED);
    expect(notice.cutAt).toBeUndefined();
    expect(notice.unreadSeconds).toBeUndefined();
  });

  it('ignores non-numeric values rather than trusting the wire', () => {
    const [notice] = withNotice([], 'Transcript Limit', CUT, { transcript_cut_at: '2066.1' });
    expect(notice.cutAt).toBeUndefined();
  });
});
