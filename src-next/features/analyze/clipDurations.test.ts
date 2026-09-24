import { describe, expect, it } from 'vitest';
import { CLIP_DURATIONS, durationOptions } from './clipDurations';
import { buildAnalyzeInit } from '../../hooks/useAnalyze';
import { id } from '../../i18n/id';
import { en } from '../../i18n/en';
import source from '../../../backend/clip_lengths.py?raw';

describe('clip durations (#34)', () => {
  it('offers 2 and 3 minutes next to the old lengths', () => {
    expect(durationOptions(id).map((o) => o.label)).toEqual(['15s', '30s', '60s', '2m', '3m']);
    expect(durationOptions(id).map((o) => o.value)).toEqual([...CLIP_DURATIONS]);
  });

  it('has a short description in both languages', () => {
    for (const t of [id, en]) {
      expect(durationOptions(t).every((o) => o.sub.trim().length > 0)).toBe(true);
    }
    expect(durationOptions(id).slice(3).map((o) => o.sub)).toEqual(['konteks', 'utuh']);
  });

  it('sends the backend value, not the label', () => {
    const init = buildAnalyzeInit({ url: 'https://youtu.be/x', duration: '180s' }, 'k');
    expect(JSON.parse(String(init.body)).duration).toBe('180s');
  });

  it('matches the list the backend accepts', () => {
    // The backend refuses anything else with 422, so the two lists must agree.
    const literal = /Duration = Literal\[([^\]]+)\]/.exec(source)?.[1] ?? '';
    const backend = [...literal.matchAll(/"([^"]+)"/g)].map((m) => m[1]);
    expect(backend).toEqual([...CLIP_DURATIONS]);
  });
});
