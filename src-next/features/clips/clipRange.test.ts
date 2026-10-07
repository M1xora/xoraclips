import { describe, expect, it } from 'vitest';
import { clipRangeFit } from './clipRange';

// The 30s preset is (20, 40) in backend/clip_lengths.py DURATIONS.
const THIRTY: [number, number] = [20, 40];

describe('clipRangeFit', () => {
  it('a clip inside the range is not marked', () => {
    expect(clipRangeFit(30, THIRTY)).toEqual({ status: 'in', off: 0, shortest: 20, longest: 40 });
  });

  it('counts both edges as inside', () => {
    expect(clipRangeFit(20, THIRTY)?.status).toBe('in');
    expect(clipRangeFit(40, THIRTY)?.status).toBe('in');
  });

  it('reports how far a long clip runs over', () => {
    // The worst case measured on backend/tests/fixtures/gemini_answers:
    // a 49s clip from the komedi fixture, asked with the 30s preset.
    expect(clipRangeFit(49, THIRTY)).toEqual({ status: 'over', off: 9, shortest: 20, longest: 40 });
  });

  it('reports how far a short clip falls under', () => {
    expect(clipRangeFit(19, THIRTY)).toEqual({ status: 'under', off: 1, shortest: 20, longest: 40 });
  });

  it('says nothing without a range (an analysis from before #94)', () => {
    expect(clipRangeFit(49, null)).toBeNull();
    expect(clipRangeFit(49, undefined)).toBeNull();
  });

  it('says nothing for a range that makes no sense', () => {
    expect(clipRangeFit(30, [40, 20])).toBeNull();
    expect(clipRangeFit(30, [Number.NaN, 40])).toBeNull();
  });

  it('says nothing for a length that is not a number', () => {
    expect(clipRangeFit(Number.NaN, THIRTY)).toBeNull();
  });

  it('works for every preset the backend offers', () => {
    expect(clipRangeFit(12, [10, 20])?.status).toBe('in');
    expect(clipRangeFit(80, [45, 75])?.status).toBe('over');
    expect(clipRangeFit(100, [90, 130])?.status).toBe('in');
    expect(clipRangeFit(120, [140, 175])?.status).toBe('under');
  });
});
