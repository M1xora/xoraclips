/**
 * Whether a clip's length falls inside the preset the user picked (#94).
 *
 * Clip bounds follow sentence edges (backend/clip_bounds.py), so a clip may
 * end up longer or shorter than the preset asks for. Nothing is cut to fit:
 * the range only marks such a clip on its card, and the user can still trim
 * it in the Studio.
 *
 * The range comes from the backend (`clip_range_seconds`), which reads it
 * from DURATIONS in backend/clip_lengths.py, so the numbers live in one
 * place. An analysis made before #94 carries no range and is never marked.
 */

export type ClipRangeStatus = 'in' | 'over' | 'under';

export interface ClipRangeFit {
  status: ClipRangeStatus;
  /** Seconds past the edge of the range; 0 when inside it. */
  off: number;
  shortest: number;
  longest: number;
}

/**
 * How `seconds` sits in `range`, or null when there is nothing to compare
 * against: no range (an older analysis), or one that makes no sense.
 */
export function clipRangeFit(
  seconds: number,
  range: readonly [number, number] | null | undefined,
): ClipRangeFit | null {
  if (!range) return null;
  const [shortest, longest] = range;
  if (!Number.isFinite(shortest) || !Number.isFinite(longest) || shortest > longest) return null;
  if (!Number.isFinite(seconds)) return null;

  // The edges count as inside: a 40s clip fits the 20-40s preset.
  if (seconds > longest) return { status: 'over', off: seconds - longest, shortest, longest };
  if (seconds < shortest) return { status: 'under', off: shortest - seconds, shortest, longest };
  return { status: 'in', off: 0, shortest, longest };
}
