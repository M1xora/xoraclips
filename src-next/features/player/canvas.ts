import type { AspectRatioOption } from '../../lib/types';

/**
 * Export canvas geometry.
 *
 * The exported video is always 1080x1920. Choosing a different aspect ratio
 * changes the shape of the video inside that canvas, not the canvas itself,
 * and ffmpeg pads the leftover space with black bars.
 *
 * Values read off backend/video_engine.py, where each ratio ends with a
 * `pad=1080:1920:0:<y>` back up to the full canvas.
 */

export const CANVAS_W = 1080;
export const CANVAS_H = 1920;

export interface VideoBox {
  /** Height of the video inside the canvas, in export pixels. */
  h: number;
  /** Distance from the top of the canvas to the video, in export pixels. */
  y: number;
}

export const VIDEO_BOX: Record<AspectRatioOption, VideoBox> = {
  '9:16': { h: 1920, y: 0 },
  '1:1': { h: 1080, y: 420 },
  '4:3': { h: 810, y: 555 },
  '16:9': { h: 608, y: 656 },
};

/** Whether this ratio leaves bars that a backdrop could fill. */
export function hasBars(ratio: AspectRatioOption): boolean {
  return VIDEO_BOX[ratio].h < CANVAS_H;
}

/** Bar height above and below the video, in export pixels. */
export function barHeights(ratio: AspectRatioOption): { top: number; bottom: number } {
  const box = VIDEO_BOX[ratio];
  return { top: box.y, bottom: CANVAS_H - box.h - box.y };
}

/**
 * Streamer presets change the layout, so the plain VIDEO_BOX above only
 * describes `streamerPreset: 'none'`.
 *
 * split_top_cam stacks two boxes of equal size (vstack) and pads the pair
 * back to 1080x1920. Values read off video_engine.py:1305-1370.
 */
export interface SplitLayout {
  /** Width of each stacked box, in export pixels. */
  w: number;
  /** Height of each stacked box, in export pixels. */
  h: number;
  /** Offset of the stacked pair inside the canvas. */
  x: number;
  y: number;
}

export const SPLIT_LAYOUT: Record<AspectRatioOption, SplitLayout> = {
  '9:16': { w: 540, h: 960, x: 270, y: 0 },
  '1:1': { w: 960, h: 960, x: 60, y: 0 },
  '4:3': { w: 1080, h: 810, x: 0, y: 150 },
  '16:9': { w: 1080, h: 608, x: 0, y: 352 },
};

/**
 * pip_corner keeps the normal VIDEO_BOX and drops a 320x240 box on top of it.
 * Values read off video_engine.py:1373-1445.
 */
export const PIP_SIZE = { w: 320, h: 240 };

export const PIP_POS: Record<AspectRatioOption, { x: number; y: number }> = {
  '9:16': { x: 736, y: 120 },
  '1:1': { x: 736, y: 444 },
  '4:3': { x: 736, y: 579 },
  '16:9': { x: 736, y: 676 },
};
