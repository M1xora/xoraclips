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
 * split_top_cam stacks two full-width boxes that fill the canvas exactly
 * (#96). The ratio the user picked does not shape them: two 9:16 boxes
 * stacked are 4.5:16 and cannot fill a 9:16 frame, which is why the old
 * layout left 270px of bar on each side. Values read off video_engine.py
 * SPLIT_CAM_W / SPLIT_CAM_H / SPLIT_GAME_H, which these must match or the
 * preview shows a layout the render does not produce.
 */
export interface SplitBox {
  /** Width in export pixels; both boxes span the canvas. */
  w: number;
  /** Height in export pixels. */
  h: number;
  /** Top edge inside the canvas. */
  y: number;
}

export interface SplitLayout {
  /** The facecam, cropped around the face. */
  cam: SplitBox;
  /** The content feed, cropped centre. */
  game: SplitBox;
}

/** 40/60: the content box gets the larger share, where the action is. */
export const SPLIT_LAYOUT: SplitLayout = {
  cam: { w: 1080, h: 768, y: 0 },
  game: { w: 1080, h: 1152, y: 768 },
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
