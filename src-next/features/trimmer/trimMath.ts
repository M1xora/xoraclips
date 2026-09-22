/**
 * Timeline maths for the trimmer.
 *
 * Kept separate from the component so the clamping rules can be tested
 * without a DOM. The rules match ClipTrimmerModal.tsx:336-411.
 */

/** Shortest clip the renderer will accept. */
export const MIN_CLIP_SECONDS = 3;

/** How far either side of the AI's pick the user may reach. */
export const CONTEXT_SECONDS = 120;

export interface Timeline {
  min: number;
  max: number;
  span: number;
}

export function buildTimeline(
  origStart: number,
  origEnd: number,
  videoDuration: number,
): Timeline {
  const total = videoDuration > 0 ? videoDuration : origEnd + CONTEXT_SECONDS;
  const min = Math.max(0, Math.floor(origStart - CONTEXT_SECONDS));
  const max = Math.min(total, Math.ceil(origEnd + CONTEXT_SECONDS));
  return { min, max, span: Math.max(1, max - min) };
}

export function timeToPercent(time: number, tl: Timeline): number {
  return Math.max(0, Math.min(100, ((time - tl.min) / tl.span) * 100));
}

export function percentToTime(pct: number, tl: Timeline): number {
  return tl.min + Math.max(0, Math.min(1, pct / 100)) * tl.span;
}

/** Start handle: snapped to whole seconds, never within 3s of the end. */
export function clampStart(candidate: number, end: number, tl: Timeline): number {
  return Math.max(tl.min, Math.min(end - MIN_CLIP_SECONDS, Math.round(candidate)));
}

/** End handle: snapped to whole seconds, never within 3s of the start. */
export function clampEnd(candidate: number, start: number, tl: Timeline): number {
  return Math.min(tl.max, Math.max(start + MIN_CLIP_SECONDS, Math.round(candidate)));
}

/** Playhead stays sub-second, unlike the handles. */
export function clampPlayhead(candidate: number, tl: Timeline): number {
  return Math.max(tl.min, Math.min(tl.max, candidate));
}

/**
 * Slides the whole window, keeping its length.
 * Hitting either edge stops the slide rather than shortening the clip.
 */
export function slideWindow(
  initialStart: number,
  duration: number,
  deltaSeconds: number,
  tl: Timeline,
): { start: number; end: number } {
  let start = Math.round(initialStart + deltaSeconds);
  let end = start + duration;

  if (start < tl.min) {
    start = tl.min;
    end = start + duration;
  }
  if (end > tl.max) {
    end = tl.max;
    start = end - duration;
  }
  return { start, end };
}
