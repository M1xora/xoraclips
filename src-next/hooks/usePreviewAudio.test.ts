import { describe, expect, it } from 'vitest';
import { bgmFade, bgmSeekTarget, FADE_SEC, needsResync } from './usePreviewAudio';

describe('bgmFade', () => {
  // video_engine.py:1692 fades out over the last 1.5s and is flat before it.
  it('is silent at the very end', () => {
    expect(bgmFade(30, 30)).toBe(0);
  });

  it('is at full volume for most of the clip', () => {
    expect(bgmFade(0, 30)).toBe(1);
    expect(bgmFade(15, 30)).toBe(1);
    expect(bgmFade(30 - FADE_SEC, 30)).toBe(1);
  });

  it('is halfway down at half the fade', () => {
    expect(bgmFade(30 - FADE_SEC / 2, 30)).toBeCloseTo(0.5, 5);
  });

  it('never leaves 0..1', () => {
    for (const e of [-5, 0, 10, 29.9, 30, 40]) {
      const v = bgmFade(e, 30);
      expect(v, `elapsed ${e}`).toBeGreaterThanOrEqual(0);
      expect(v, `elapsed ${e}`).toBeLessThanOrEqual(1);
    }
  });

  it('falls monotonically through the fade', () => {
    let prev = 1;
    for (let e = 28.5; e <= 30; e += 0.1) {
      const v = bgmFade(e, 30);
      expect(v).toBeLessThanOrEqual(prev + 1e-9);
      prev = v;
    }
  });

  it('handles a clip shorter than the fade', () => {
    // A 1s clip is inside the fade from the first frame.
    expect(bgmFade(0, 1)).toBeCloseTo(1 / FADE_SEC, 5);
    expect(bgmFade(1, 1)).toBe(0);
  });
});

describe('bgmSeekTarget', () => {
  it('starts at the chosen offset', () => {
    expect(bgmSeekTarget(12, 0, 180)).toBe(12);
  });

  it('advances with the clip', () => {
    expect(bgmSeekTarget(12, 8, 180)).toBe(20);
  });

  it('wraps when the track runs out, as -stream_loop does', () => {
    // A 30s track, starting 20s in, 15s into the clip: 35s wraps to 5s.
    expect(bgmSeekTarget(20, 15, 30)).toBeCloseTo(5, 5);
  });

  it('wraps repeatedly for a short track', () => {
    expect(bgmSeekTarget(0, 25, 10)).toBeCloseTo(5, 5);
  });

  it('falls back when the duration is not known yet', () => {
    // Audio metadata is NaN until it loads; seeking should still be sane.
    expect(bgmSeekTarget(5, 3, Number.NaN)).toBe(8);
    expect(bgmSeekTarget(5, 3, 0)).toBe(8);
  });

  it('never returns a negative time', () => {
    for (const len of [10, 30, 180, Number.NaN]) {
      expect(bgmSeekTarget(0, 0, len)).toBeGreaterThanOrEqual(0);
    }
  });
});

describe('needsResync (#40)', () => {
  it('leaves small drift alone, so the music does not stutter', () => {
    expect(needsResync(12.3, 12.0)).toBe(false);
  });

  it('moves the music back after "replay from start"', () => {
    // Video back at 0s, music still 20s in.
    expect(needsResync(20, bgmSeekTarget(0, 0, 180))).toBe(true);
  });
});
