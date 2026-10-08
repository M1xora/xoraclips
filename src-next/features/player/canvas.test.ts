import { describe, expect, it } from 'vitest';
import {
  barHeights,
  CANVAS_H,
  CANVAS_W,
  hasBars,
  PIP_POS,
  PIP_SIZE,
  SPLIT_LAYOUT,
  SPLIT_CAM_BG_SIZE,
  SPLIT_CAM_SOURCE_SHARE,
  splitCamBgSize,
  splitCamSourceShare,
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

describe('split_top_cam layout (#96)', () => {
  // video_engine.py stacks two full-width boxes that already fill the canvas,
  // so there is nothing to pad. SPLIT_CAM_W / SPLIT_CAM_H / SPLIT_GAME_H.
  it('stacks a 1080x768 cam over a 1080x1152 feed', () => {
    expect(SPLIT_LAYOUT.cam).toEqual({ w: 1080, h: 768, y: 0 });
    expect(SPLIT_LAYOUT.game).toEqual({ w: 1080, h: 1152, y: 768 });
  });

  it('fills the canvas exactly, leaving no bars', () => {
    const { cam, game } = SPLIT_LAYOUT;
    expect(cam.w).toBe(CANVAS_W);
    expect(game.w).toBe(CANVAS_W);
    expect(cam.h + game.h).toBe(CANVAS_H);
  });

  it('puts the feed directly under the cam, with no gap or overlap', () => {
    expect(SPLIT_LAYOUT.game.y).toBe(SPLIT_LAYOUT.cam.h);
  });

  // Issue #105: the crop follows the detected face so a small facecam does
  // not drown in the room around it. These shares must match
  // video_engine.split_cam_crop_share exactly, or the preview shows a framing
  // the render will not produce.
  it('matches the backend share for the three sample faces', () => {
    expect(splitCamSourceShare(0.085)).toBeCloseTo(0.2125, 4);   // 163px face
    expect(splitCamSourceShare(0.156)).toBeCloseTo(0.39, 4);     // 300px face
    expect(splitCamSourceShare(0.26)).toBeCloseTo(0.4351, 4);    // 499px face
  });

  it('falls back to the fixed zoom when no face was found', () => {
    expect(splitCamSourceShare(0)).toBeCloseTo(SPLIT_CAM_SOURCE_SHARE, 6);
    expect(splitCamSourceShare(-1)).toBeCloseTo(SPLIT_CAM_SOURCE_SHARE, 6);
  });

  it('lets a manual zoom win over the face', () => {
    expect(splitCamSourceShare(0.085, 0.5)).toBeCloseTo(0.3955, 4);
  });

  it('caps a large face so the crop still has room to move', () => {
    // Past the cap the share stops growing, and stays under the full width.
    expect(splitCamSourceShare(0.6)).toBeCloseTo(splitCamSourceShare(0.9), 6);
    expect(splitCamSourceShare(0.9)).toBeLessThan(1);
  });

  it('turns a share into a CSS background-size', () => {
    expect(splitCamBgSize(0)).toBe(SPLIT_CAM_BG_SIZE);
    expect(splitCamBgSize(0.085)).toBe('471%');
  });

  it('gives the feed the larger share, where the action is', () => {
    expect(SPLIT_LAYOUT.game.h).toBeGreaterThan(SPLIT_LAYOUT.cam.h);
  });

  it('keeps both heights a multiple of 16 for the encoder', () => {
    expect(SPLIT_LAYOUT.cam.h % 16).toBe(0);
    expect(SPLIT_LAYOUT.game.h % 16).toBe(0);
  });

  it('is the same whatever ratio is picked, so the ratio control is moot', () => {
    // The old layout shaped the boxes from the ratio, which is why 9:16 only
    // covered half the canvas. There is now one layout, not four.
    expect(Object.keys(SPLIT_LAYOUT).sort()).toEqual(['cam', 'game']);
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

