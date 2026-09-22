import { describe, expect, it } from 'vitest';
import {
  buildTimeline,
  clampEnd,
  clampPlayhead,
  clampStart,
  CONTEXT_SECONDS,
  MIN_CLIP_SECONDS,
  percentToTime,
  slideWindow,
  timeToPercent,
} from './trimMath';

const tl = buildTimeline(200, 230, 600);

describe('buildTimeline', () => {
  it('reaches two minutes either side of the clip', () => {
    expect(tl.min).toBe(200 - CONTEXT_SECONDS);
    expect(tl.max).toBe(230 + CONTEXT_SECONDS);
  });

  it('never starts before the video does', () => {
    expect(buildTimeline(10, 40, 600).min).toBe(0);
  });

  it('never runs past the end of the video', () => {
    expect(buildTimeline(500, 560, 600).max).toBe(600);
  });

  it('copes with an unknown duration', () => {
    const t = buildTimeline(100, 130, 0);
    expect(t.max).toBe(130 + CONTEXT_SECONDS);
    expect(t.span).toBeGreaterThan(0);
  });

  it('always has a positive span', () => {
    expect(buildTimeline(0, 0, 0).span).toBeGreaterThan(0);
  });
});

describe('time and percent convert both ways', () => {
  it('maps the ends to 0 and 100', () => {
    expect(timeToPercent(tl.min, tl)).toBe(0);
    expect(timeToPercent(tl.max, tl)).toBe(100);
  });

  it('clamps out-of-range times', () => {
    expect(timeToPercent(-999, tl)).toBe(0);
    expect(timeToPercent(99999, tl)).toBe(100);
  });

  it('round-trips', () => {
    for (const t of [tl.min, 200, 230, tl.max]) {
      expect(percentToTime(timeToPercent(t, tl), tl)).toBeCloseTo(t, 5);
    }
  });
});

describe('handle clamping', () => {
  it('keeps the clip at least three seconds long', () => {
    expect(clampStart(229, 230, tl)).toBe(230 - MIN_CLIP_SECONDS);
    expect(clampEnd(201, 200, tl)).toBe(200 + MIN_CLIP_SECONDS);
  });

  it('keeps the handles inside the timeline', () => {
    expect(clampStart(-999, 230, tl)).toBe(tl.min);
    expect(clampEnd(99999, 200, tl)).toBe(tl.max);
  });

  it('snaps handles to whole seconds', () => {
    expect(Number.isInteger(clampStart(205.7, 230, tl))).toBe(true);
    expect(Number.isInteger(clampEnd(225.2, 200, tl))).toBe(true);
  });

  it('leaves the playhead sub-second', () => {
    // Deliberately different from the handles, so scrubbing stays smooth.
    expect(clampPlayhead(205.25, tl)).toBeCloseTo(205.25, 5);
  });

  it('keeps the playhead inside the timeline', () => {
    expect(clampPlayhead(-50, tl)).toBe(tl.min);
    expect(clampPlayhead(99999, tl)).toBe(tl.max);
  });
});

describe('slideWindow', () => {
  it('keeps the clip length when moved', () => {
    const { start, end } = slideWindow(200, 30, 15, tl);
    expect(end - start).toBe(30);
    expect(start).toBe(215);
  });

  it('keeps the length when it hits the left edge', () => {
    const { start, end } = slideWindow(200, 30, -9999, tl);
    expect(start).toBe(tl.min);
    expect(end - start).toBe(30);
  });

  it('keeps the length when it hits the right edge', () => {
    const { start, end } = slideWindow(200, 30, 9999, tl);
    expect(end).toBe(tl.max);
    expect(end - start).toBe(30);
  });

  it('moves backwards too', () => {
    expect(slideWindow(200, 30, -20, tl).start).toBe(180);
  });

  it('stays inside the timeline whatever the delta', () => {
    for (const delta of [-500, -60, 0, 60, 500]) {
      const { start, end } = slideWindow(200, 30, delta, tl);
      expect(start).toBeGreaterThanOrEqual(tl.min);
      expect(end).toBeLessThanOrEqual(tl.max);
    }
  });
});
