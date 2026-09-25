import { describe, expect, it } from 'vitest';
import {
  buildTimeline,
  clampEnd,
  clampPlayhead,
  clampStart,
  CONTEXT_SECONDS,
  lineEdges,
  nudgeEnd,
  nudgeStart,
  playbackStretch,
  playedPastEnd,
  MIN_CLIP_SECONDS,
  percentToTime,
  slideWindow,
  timeToPercent,
  withEnd,
  withStart,
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

describe('withStart / withEnd (#56)', () => {
  it('keeps hundredths instead of rounding to whole seconds', () => {
    expect(withStart(210.284, 230, tl)).toEqual({ start: 210.28, end: 230 });
    expect(withEnd(225.678, 210, tl)).toEqual({ start: 210, end: 225.68 });
  });

  it('moves the end along when the new start comes within 3s of it', () => {
    expect(withStart(229, 230, tl)).toEqual({ start: 229, end: 229 + MIN_CLIP_SECONDS });
    expect(withStart(300, 230, tl)).toEqual({ start: 300, end: 300 + MIN_CLIP_SECONDS });
  });

  it('moves the start back when the new end comes within 3s of it', () => {
    expect(withEnd(211, 210, tl)).toEqual({ start: 211 - MIN_CLIP_SECONDS, end: 211 });
  });

  it('stays inside the timeline', () => {
    expect(withStart(0, 230, tl).start).toBe(tl.min);
    expect(withEnd(10_000, 210, tl).end).toBe(tl.max);
    expect(withStart(10_000, 230, tl)).toEqual({ start: tl.max - MIN_CLIP_SECONDS, end: tl.max });
  });
});

describe('lineEdges (#56)', () => {
  it('ends a rolling auto caption at the next line start', () => {
    const edges = lineEdges([
      { start: 15.08, end: 19.24, text: 'yang namanya sehat itu susah kalau sakit' },
      { start: 17.28, end: 21.72, text: 'mah gampang gitu kita tinggal keluar' },
      { start: 19.24, end: 23.24, text: 'rumah langsung ketemu' },
    ]);
    expect(edges.map((l) => [l.start, l.end])).toEqual([[15.08, 17.28], [17.28, 19.24], [19.24, 23.24]]);
  });

  it('sorts lines and lets lines sharing a start look past each other', () => {
    const edges = lineEdges([
      { start: 10, end: 20, text: 'c' },
      { start: 5, end: 12, text: 'a' },
      { start: 5, end: 7, text: 'b' },
    ]);
    expect(edges.map((l) => [l.text, l.end])).toEqual([['a', 10], ['b', 7], ['c', 20]]);
  });

  it('drops empty lines and never ends a line before it starts', () => {
    const edges = lineEdges([
      { start: 1, end: 2, text: '  ' },
      { start: 3, end: 2, text: 'rusak' },
    ]);
    expect(edges).toEqual([{ start: 3, end: 3, text: 'rusak' }]);
  });
});

describe('playbackStretch (#56)', () => {
  it('starts when playback starts, and again after a jump', () => {
    expect(playbackStretch(null, 30, 30.2, true)).toBe(30.2);
    expect(playbackStretch(30.2, 30.2, 30.4, true)).toBe(30.2);
    expect(playbackStretch(30.2, 31, 47, true)).toBe(47); // a seek
    expect(playbackStretch(30.2, 31, 31.2, false)).toBeNull();
  });
});

describe('playedPastEnd (#56)', () => {
  it('stops playback that began inside the selection at its end', () => {
    expect(playedPastEnd(212, 229.9, 230.1, 200, 230)).toBe(true);
    expect(playedPastEnd(200, 229.9, 230, 200, 230)).toBe(true);
  });

  it('leaves playback that began before the selection alone', () => {
    // The lead-in: started at 150, flowed through the selection.
    expect(playedPastEnd(150, 229.9, 230.1, 200, 230)).toBe(false);
  });

  it('leaves playback that began past the end alone', () => {
    expect(playedPastEnd(231, 231, 232, 200, 230)).toBe(false);
  });

  it('ignores a jump across the end', () => {
    expect(playedPastEnd(205, 205, 240, 200, 240)).toBe(false);
  });

  it('is false while not playing', () => {
    expect(playedPastEnd(null, 229.9, 230.1, 200, 230)).toBe(false);
  });
});

describe('nudgeStart / nudgeEnd (#56)', () => {
  it('keeps hundredths and stops 3s before the other side', () => {
    expect(nudgeStart(214.28, 230, tl)).toBe(214.28);
    expect(nudgeStart(229, 230, tl)).toBe(230 - MIN_CLIP_SECONDS);
    expect(nudgeEnd(215.5, 214.28, tl)).toBe(217.28);
    expect(nudgeEnd(225.55, 210, tl)).toBe(225.55);
  });
});

describe('slideWindow keeps a precise start (#56)', () => {
  it('moves in whole seconds without rounding the start', () => {
    expect(slideWindow(210.28, 10, 3.4, tl)).toEqual({ start: 213.28, end: 223.28 });
  });
});
