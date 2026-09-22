import { beforeEach, describe, expect, it } from 'vitest';
import { effectiveTitle, loadMarks, markedClips, saveMarks, withClipIds } from './clipIdentity';
import type { AnalyzeResponse, ViralClip } from '../../lib/types';

function clip(partial: Partial<ViralClip> & { start_time: number; end_time: number }): ViralClip {
  return {
    id: '',
    title: 'A clip',
    virality_score: 80,
    key_quotes: [],
    transcript: '',
    ...partial,
  };
}

function result(clips: ViralClip[]): AnalyzeResponse {
  return {
    video_id: 'vid123',
    title: 'Video',
    duration: 600,
    heatmap: [],
    summary: '',
    clips,
  };
}

// jsdom is not installed, so stand in a minimal localStorage.
beforeEach(() => {
  const store = new Map<string, string>();
  globalThis.localStorage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
    key: (i: number) => [...store.keys()][i] ?? null,
    get length() {
      return store.size;
    },
  } as Storage;
});

describe('withClipIds', () => {
  it('gives every clip an id', () => {
    const r = withClipIds(result([clip({ start_time: 0, end_time: 10 }), clip({ start_time: 20, end_time: 30 })]));
    expect(r.clips.every((c) => c.id.length > 0)).toBe(true);
  });

  it('gives distinct ids', () => {
    const r = withClipIds(result([clip({ start_time: 0, end_time: 10 }), clip({ start_time: 20, end_time: 30 })]));
    expect(new Set(r.clips.map((c) => c.id)).size).toBe(2);
  });

  it('keeps ids that already exist', () => {
    const r = withClipIds(result([clip({ id: 'keep-me', start_time: 0, end_time: 10 })]));
    expect(r.clips[0].id).toBe('keep-me');
  });
});

describe('loadMarks migration', () => {
  const clips = [
    clip({ id: 'id-a', start_time: 12.5, end_time: 47 }),
    clip({ id: 'id-b', start_time: 100, end_time: 130 }),
  ];

  it('converts legacy start_end keys to clip ids', () => {
    localStorage.setItem('marked_clips_vid123', JSON.stringify({ '12.5_47': true }));
    expect(loadMarks('vid123', clips)).toEqual({ 'id-a': true });
  });

  it('persists the migration so it runs once', () => {
    localStorage.setItem('marked_clips_vid123', JSON.stringify({ '12.5_47': true }));
    loadMarks('vid123', clips);
    expect(JSON.parse(localStorage.getItem('marked_clips_vid123')!)).toEqual({ 'id-a': true });
  });

  it('drops legacy keys with no matching clip', () => {
    localStorage.setItem('marked_clips_vid123', JSON.stringify({ '999_1000': true }));
    expect(loadMarks('vid123', clips)).toEqual({});
  });

  it('leaves id-based marks untouched', () => {
    localStorage.setItem('marked_clips_vid123', JSON.stringify({ 'id-b': true }));
    expect(loadMarks('vid123', clips)).toEqual({ 'id-b': true });
  });

  it('handles a mix of both schemes', () => {
    localStorage.setItem('marked_clips_vid123', JSON.stringify({ '12.5_47': true, 'id-b': true }));
    expect(loadMarks('vid123', clips)).toEqual({ 'id-a': true, 'id-b': true });
  });

  it('ignores false values', () => {
    localStorage.setItem('marked_clips_vid123', JSON.stringify({ '12.5_47': false }));
    expect(loadMarks('vid123', clips)).toEqual({});
  });

  it('returns empty on corrupt json rather than throwing', () => {
    localStorage.setItem('marked_clips_vid123', '{not json');
    expect(loadMarks('vid123', clips)).toEqual({});
  });

  it('survives a trim, which is the bug this replaces', () => {
    localStorage.setItem('marked_clips_vid123', JSON.stringify({ '12.5_47': true }));
    const marks = loadMarks('vid123', clips);

    // Trimming shifts start/end. Under the old scheme the key no longer
    // matched and the mark silently vanished.
    const trimmed = [{ ...clips[0], start_time: 15, end_time: 44 }, clips[1]];
    expect(markedClips(trimmed, marks)).toHaveLength(1);
    expect(markedClips(trimmed, marks)[0].id).toBe('id-a');
  });
});

describe('saveMarks', () => {
  it('round-trips', () => {
    saveMarks('vid123', { 'id-a': true });
    expect(loadMarks('vid123', [clip({ id: 'id-a', start_time: 0, end_time: 5 })])).toEqual({ 'id-a': true });
  });

  it('ignores an empty video id', () => {
    saveMarks('', { 'id-a': true });
    expect(localStorage.length).toBe(0);
  });
});

describe('effectiveTitle', () => {
  const base = clip({ id: 'x', start_time: 0, end_time: 5, title: 'Base', title_suggestion: 'Suggested' });

  it('prefers the live custom title', () => {
    expect(effectiveTitle(base, { x: 'Live edit' })).toBe('Live edit');
  });

  it('falls back to the persisted custom title', () => {
    expect(effectiveTitle({ ...base, custom_title: 'Saved' }, {})).toBe('Saved');
  });

  it('then the suggestion, matching backend precedence', () => {
    expect(effectiveTitle(base, {})).toBe('Suggested');
  });

  it('then the plain title', () => {
    expect(effectiveTitle({ ...base, title_suggestion: undefined }, {})).toBe('Base');
  });

  it('ignores whitespace-only overrides', () => {
    expect(effectiveTitle(base, { x: '   ' })).toBe('Suggested');
  });
});
