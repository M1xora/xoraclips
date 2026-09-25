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

// ---------------------------------------------------------------------------
// Precise edits (#56): typed times and transcript lines are not rounded to
// whole seconds. Rounding a line start down would pull in the end of the
// line before it.

const round2 = (t: number) => Math.round(t * 100) / 100;

/**
 * "83", "83.5", "1:23", "1:23.5" or "1:01:23" to seconds; null for anything
 * else. A comma works as the decimal mark too ("1:23,5").
 */
export function parseTimecode(text: string): number | null {
  const raw = text.trim().replace(',', '.');
  if (!/^\d+(:\d{1,2}){0,2}(\.\d+)?$/.test(raw)) return null;
  const parts = raw.split(':');
  const seconds = Number(parts.pop());
  if (parts.length > 0 && seconds >= 60) return null;
  const minutes = parts.length > 0 ? Number(parts.pop()) : 0;
  if (parts.length > 0 && minutes >= 60) return null;
  const hours = parts.length > 0 ? Number(parts.pop()) : 0;
  return hours * 3600 + minutes * 60 + seconds;
}

/**
 * A new start, kept inside the timeline. When it lands within 3s of the end
 * (or past it), the end moves along instead of the start being refused.
 */
export function withStart(
  candidate: number,
  end: number,
  tl: Timeline,
): { start: number; end: number } {
  const start = round2(Math.max(tl.min, Math.min(tl.max - MIN_CLIP_SECONDS, candidate)));
  return { start, end: Math.min(tl.max, Math.max(end, start + MIN_CLIP_SECONDS)) };
}

/** A new end; the start moves back when the end lands within 3s of it. */
export function withEnd(
  candidate: number,
  start: number,
  tl: Timeline,
): { start: number; end: number } {
  const end = round2(Math.min(tl.max, Math.max(tl.min + MIN_CLIP_SECONDS, candidate)));
  return { start: Math.max(tl.min, Math.min(start, end - MIN_CLIP_SECONDS)), end };
}

export interface LineEdge {
  start: number;
  end: number;
  text: string;
}

/**
 * Transcript lines sorted by start, each ending no later than the next line
 * that starts after it. YouTube auto captions roll: a line's own end runs
 * into the line after next, so "end at this line" would cut into the next
 * sentence. The same rule as backend captions._resolve_line_times.
 */
export function lineEdges(lines: { start: number; end: number; text: string }[]): LineEdge[] {
  const sorted = lines
    .filter((l) => l.text.trim() && Number.isFinite(l.start) && Number.isFinite(l.end))
    .map((l) => ({ start: l.start, end: l.end, text: l.text.trim() }))
    .sort((a, b) => a.start - b.start);
  // nextLater[i]: start of the first following line that begins strictly
  // after line i (lines sharing a start look past each other).
  const nextLater: number[] = sorted.map(() => Infinity);
  for (let i = sorted.length - 2; i >= 0; i--) {
    const next = sorted[i + 1].start;
    nextLater[i] = next > sorted[i].start ? next : nextLater[i + 1];
  }
  sorted.forEach((line, i) => {
    line.end = Math.max(line.start, Math.min(line.end, nextLater[i]));
  });
  return sorted;
}

/** True when playback just ran from inside the selection to its end or past it. */
export function crossedEnd(previous: number, now: number, end: number): boolean {
  return previous < end && now >= end;
}

/** Seconds as "1:23", "1:23.5" or "1:01:23.25": what the time fields show. */
export function formatTrimTime(seconds: number): string {
  const total = Math.max(0, round2(seconds));
  const whole = Math.floor(total);
  const fraction = round2(total - whole);
  const h = Math.floor(whole / 3600);
  const m = Math.floor((whole % 3600) / 60);
  const sec = whole % 60;
  const ss = String(sec).padStart(2, '0');
  const tail = fraction > 0 ? String(fraction.toFixed(2)).slice(1).replace(/0+$/, '') : '';
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${ss}${tail}` : `${m}:${ss}${tail}`;
}
