import { describe, expect, it } from 'vitest';
import {
  barHeights,
  CANVAS_H,
  CANVAS_W,
  hasBars,
  PIP_POS,
  PIP_SIZE,
  SPLIT_LAYOUT,
  VIDEO_BOX,
} from './canvas';
import type { AspectRatioOption } from '../../lib/types';

const RATIOS: AspectRatioOption[] = ['9:16', '1:1', '4:3', '16:9'];

describe('export canvas', () => {
  it('is 1080x1920 whatever the ratio', () => {
    expect(CANVAS_W).toBe(1080);
    expect(CANVAS_H).toBe(1920);
  });
});

describe('video box', () => {
  // Straight from video_engine.py, where each branch ends in
  // pad=1080:1920:0:<y>. If the backend changes, these fail.
  it.each([
    ['9:16', 1920, 0],
    ['1:1', 1080, 420],
    ['4:3', 810, 555],
    ['16:9', 608, 656],
  ] as const)('%s is %dpx tall at y=%d', (ratio, h, y) => {
    expect(VIDEO_BOX[ratio]).toEqual({ h, y });
  });

  it('never exceeds the canvas', () => {
    for (const r of RATIOS) {
      const box = VIDEO_BOX[r];
      expect(box.y + box.h).toBeLessThanOrEqual(CANVAS_H);
    }
  });

  it('centres the video vertically', () => {
    // ffmpeg's pad offsets happen to centre it; a value that did not would
    // mean the preview and the export disagree.
    for (const r of RATIOS) {
      const { top, bottom } = barHeights(r);
      expect(Math.abs(top - bottom), `${r} is off centre`).toBeLessThanOrEqual(1);
    }
  });

  it('matches the width-derived height for each ratio', () => {
    // A 1:1 video 1080 wide must be 1080 tall, 4:3 must be 810, and so on.
    const expected: Record<AspectRatioOption, number> = {
      '9:16': 1920,
      '1:1': CANVAS_W,
      '4:3': Math.round((CANVAS_W * 3) / 4),
      '16:9': Math.round((CANVAS_W * 9) / 16),
    };
    for (const r of RATIOS) {
      // 16:9 rounds to 608 in the backend against 607.5 exact.
      expect(Math.abs(VIDEO_BOX[r].h - expected[r]), `${r}`).toBeLessThanOrEqual(1);
    }
  });
});

describe('bars', () => {
  it('9:16 is full bleed, so it has none', () => {
    expect(hasBars('9:16')).toBe(false);
    expect(barHeights('9:16')).toEqual({ top: 0, bottom: 0 });
  });

  it('every other ratio has them', () => {
    for (const r of ['1:1', '4:3', '16:9'] as const) {
      expect(hasBars(r), `${r} should have bars`).toBe(true);
    }
  });

  it('grows the bars as the video gets wider', () => {
    // A wider video is shorter, so more of the canvas is bar.
    expect(barHeights('1:1').top).toBeLessThan(barHeights('4:3').top);
    expect(barHeights('4:3').top).toBeLessThan(barHeights('16:9').top);
  });

  it('accounts for the whole canvas', () => {
    for (const r of RATIOS) {
      const { top, bottom } = barHeights(r);
      expect(top + VIDEO_BOX[r].h + bottom).toBe(CANVAS_H);
    }
  });
});

describe('preview scaling', () => {
  const FRAME_W = 288;
  const SCALE = FRAME_W / CANVAS_W;

  it('keeps the preview frame at 9:16', () => {
    const frameH = Math.round((FRAME_W * CANVAS_H) / CANVAS_W);
    expect(frameH).toBe(512);
    expect(frameH / FRAME_W).toBeCloseTo(16 / 9, 2);
  });

  it('scales the video box proportionally', () => {
    // 1:1 occupies just over half the canvas height, before and after.
    const scaled = Math.round(VIDEO_BOX['1:1'].h * SCALE);
    expect(scaled / 512).toBeCloseTo(1080 / 1920, 2);
  });

  it('never pushes the scaled box past the frame', () => {
    const frameH = Math.round((FRAME_W * CANVAS_H) / CANVAS_W);
    for (const r of RATIOS) {
      const h = Math.round(VIDEO_BOX[r].h * SCALE);
      const y = Math.round(VIDEO_BOX[r].y * SCALE);
      expect(y + h, `${r} overflows`).toBeLessThanOrEqual(frameH + 1);
    }
  });
});

describe('split_top_cam layout', () => {
  // video_engine.py stacks two identical boxes then pads back to 1080x1920.
  it.each([
    ['9:16', 540, 960, 270, 0],
    ['1:1', 960, 960, 60, 0],
    ['4:3', 1080, 810, 0, 150],
    ['16:9', 1080, 608, 0, 352],
  ] as const)('%s stacks %dx%d at (%d,%d)', (ratio, w, h, x, y) => {
    expect(SPLIT_LAYOUT[ratio]).toEqual({ w, h, x, y });
  });

  it('fits both stacked boxes inside the canvas', () => {
    for (const r of RATIOS) {
      const s = SPLIT_LAYOUT[r];
      expect(s.y + s.h * 2, `${r} overflows vertically`).toBeLessThanOrEqual(CANVAS_H);
      expect(s.x + s.w, `${r} overflows horizontally`).toBeLessThanOrEqual(CANVAS_W);
    }
  });

  it('centres the stacked pair', () => {
    // ffmpeg's pad offsets centre the pair; anything else means the preview
    // and the export disagree.
    for (const r of RATIOS) {
      const s = SPLIT_LAYOUT[r];
      expect(CANVAS_W - s.w - s.x, `${r} off centre horizontally`).toBe(s.x);
      expect(CANVAS_H - s.h * 2 - s.y, `${r} off centre vertically`).toBe(s.y);
    }
  });

  it('keeps each box at the chosen aspect ratio', () => {
    const expected: Record<AspectRatioOption, number> = {
      '9:16': 9 / 16,
      '1:1': 1,
      '4:3': 4 / 3,
      '16:9': 16 / 9,
    };
    for (const r of RATIOS) {
      const s = SPLIT_LAYOUT[r];
      expect(s.w / s.h, `${r}`).toBeCloseTo(expected[r], 2);
    }
  });
});

describe('pip_corner layout', () => {
  it.each([
    ['9:16', 736, 120],
    ['1:1', 736, 444],
    ['4:3', 736, 579],
    ['16:9', 736, 676],
  ] as const)('%s places the pip box at (%d,%d)', (ratio, x, y) => {
    expect(PIP_POS[ratio]).toEqual({ x, y });
  });

  it('keeps the pip box inside the canvas', () => {
    for (const r of RATIOS) {
      const p = PIP_POS[r];
      expect(p.x + PIP_SIZE.w, `${r} overflows horizontally`).toBeLessThanOrEqual(CANVAS_W);
      expect(p.y + PIP_SIZE.h, `${r} overflows vertically`).toBeLessThanOrEqual(CANVAS_H);
    }
  });

  it('keeps the pip box inside the video, not on a black bar', () => {
    // The pip sits over the content. If it drifted onto a bar it would look
    // detached from the video.
    for (const r of RATIOS) {
      const box = VIDEO_BOX[r];
      const p = PIP_POS[r];
      expect(p.y, `${r} pip starts above the video`).toBeGreaterThanOrEqual(box.y);
      expect(p.y + PIP_SIZE.h, `${r} pip ends below the video`).toBeLessThanOrEqual(
        box.y + box.h,
      );
    }
  });

  it('leaves pip_corner using the normal video box', () => {
    // Unlike split_top_cam, pip does not resize the main video.
    expect(VIDEO_BOX['1:1']).toEqual({ h: 1080, y: 420 });
  });
});

describe('split canvas usage', () => {
  /** Share of the 1080x1920 canvas the two stacked boxes actually cover. */
  function coverage(ratio: AspectRatioOption): number {
    const s = SPLIT_LAYOUT[ratio];
    return (s.w * s.h * 2) / (CANVAS_W * CANVAS_H);
  }

  it('fills half the canvas at 9:16, which is why the UI warns', () => {
    // Two 540x960 boxes in a 1080x1920 canvas. Verified on a real render:
    // the video edge lands at x=810, leaving 270px of bar each side.
    expect(coverage('9:16')).toBeCloseTo(0.5, 2);
  });

  it('fills most of the canvas at 1:1, the ratio the warning suggests', () => {
    expect(coverage('1:1')).toBeGreaterThan(0.85);
  });

  it('makes 1:1 the best choice for a split layout', () => {
    const best = RATIOS.reduce((a, b) => (coverage(a) >= coverage(b) ? a : b));
    expect(best).toBe('1:1');
  });

  it('leaves 9:16 the worst choice', () => {
    const worst = RATIOS.reduce((a, b) => (coverage(a) <= coverage(b) ? a : b));
    expect(worst).toBe('9:16');
  });

  it('never covers more than the whole canvas', () => {
    for (const r of RATIOS) {
      expect(coverage(r), `${r}`).toBeLessThanOrEqual(1);
    }
  });
});
