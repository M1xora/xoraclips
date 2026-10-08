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
 * How much of the source width the cam crop keeps (video_engine.py
 * SPLIT_CAM_ZOOM, applied to the widest crop of the cam's shape). The preview
 * zooms its still by the inverse so it frames the face as the render does.
 *
 * Used when no face was detected, matching the backend's own fallback.
 */
export const SPLIT_CAM_SOURCE_SHARE = (1080 / 768) * (9 / 16) * 0.65;

/** video_engine.py SPLIT_CAM_FACE_MARGIN / SPLIT_CAM_MAX_SHARE (issue #105). */
const SPLIT_CAM_FACE_MARGIN = 2.5;
const SPLIT_CAM_MAX_SHARE = 0.55;

/**
 * The share of the source width the cam crop keeps, given the detected face.
 *
 * Mirrors `video_engine.split_cam_crop_share`: the crop follows the face's own
 * width so a small facecam does not drown in the room around it. The preview
 * has to do the same arithmetic or it shows a framing the render will not
 * produce — the bug the aspect-ratio preview had before #96.
 *
 * `faceW` is the face's width as a share of the frame, 0 when none was found.
 * `zoom` is the Studio's manual override and wins over the face.
 */
export function splitCamSourceShare(faceW: number, zoom?: number | null): number {
  if (zoom != null) return Math.max(0.05, Math.min(1, zoom)) * (1080 / 768) * (9 / 16);
  if (faceW <= 0) return SPLIT_CAM_SOURCE_SHARE;
  // The widest cam-shaped crop, as a share of the source width: the backend's
  // min(iw, ih*1080/768) on a 16:9 source.
  const widest = Math.min(1, (9 / 16) * (1080 / 768));
  const share = Math.min((faceW / widest) * SPLIT_CAM_FACE_MARGIN,
                         (SPLIT_CAM_MAX_SHARE * (9 / 16) * (1080 / 768)) / widest, 1);
  return Math.max(0.05, share) * widest;
}

/** The CSS background-size for a cam crop of that share, e.g. "194%". */
export function splitCamBgSize(faceW: number, zoom?: number | null): string {
  return `${Math.round(100 / splitCamSourceShare(faceW, zoom))}%`;
}

/** The CSS background-size that matches the no-face crop, e.g. "194%". */
export const SPLIT_CAM_BG_SIZE = `${Math.round(100 / SPLIT_CAM_SOURCE_SHARE)}%`;

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
