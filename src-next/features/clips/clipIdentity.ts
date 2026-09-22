import type { AnalyzeResponse, ViralClip } from '../../lib/types';

/**
 * Clip identity and marked-clip persistence.
 *
 * The backend sends no id for a clip (see the ViralClip schema in
 * backend/main.py). The previous frontend keyed marks on
 * `${start_time}_${end_time}`, which shifts the moment a clip is trimmed, so
 * marks silently detached from their clip. Ids are synthesised here once,
 * when results arrive, and then travel with the cached result.
 */

/** Marks are stored per video under this prefix. */
const MARK_PREFIX = 'marked_clips_';

/** Matches the old `12.5_47` style key so it can be migrated. */
const LEGACY_KEY = /^\d+(\.\d+)?_\d+(\.\d+)?$/;

function newId(): string {
  // randomUUID needs a secure context; fall back for plain http origins.
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `clip_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * Gives every clip an id, preserving any the cache already carries.
 * Safe to call on a cached result that was stored before ids existed.
 */
export function withClipIds(result: AnalyzeResponse): AnalyzeResponse {
  let changed = false;

  const clips = result.clips.map((clip) => {
    if (clip.id) return clip;
    changed = true;
    return { ...clip, id: newId() };
  });

  return changed ? { ...result, clips } : result;
}

export type MarkMap = Record<string, boolean>;

/**
 * Converts marks written under the old start_end scheme to clip ids.
 * Clips are matched on the exact start/end the old key encoded.
 */
function migrateLegacyMarks(raw: MarkMap, clips: ViralClip[]): { marks: MarkMap; migrated: boolean } {
  const marks: MarkMap = {};
  let migrated = false;

  for (const [key, value] of Object.entries(raw)) {
    if (!value) continue;

    if (!LEGACY_KEY.test(key)) {
      marks[key] = true; // Already an id.
      continue;
    }

    const [start, end] = key.split('_').map(Number);
    const match = clips.find((c) => c.start_time === start && c.end_time === end);
    if (match) {
      marks[match.id] = true;
      migrated = true;
    }
    // A legacy key with no matching clip is dropped: the clip it pointed at
    // no longer exists in this result.
  }

  return { marks, migrated };
}

/** Reads marks for a video, migrating the old key scheme on the way. */
export function loadMarks(videoId: string, clips: ViralClip[]): MarkMap {
  if (!videoId) return {};

  let raw: MarkMap;
  try {
    const stored = localStorage.getItem(MARK_PREFIX + videoId);
    if (!stored) return {};
    raw = JSON.parse(stored) as MarkMap;
  } catch {
    return {};
  }

  const { marks, migrated } = migrateLegacyMarks(raw, clips);
  if (migrated) saveMarks(videoId, marks);
  return marks;
}

export function saveMarks(videoId: string, marks: MarkMap): void {
  if (!videoId) return;
  try {
    localStorage.setItem(MARK_PREFIX + videoId, JSON.stringify(marks));
  } catch {
    // Quota or blocked storage: marks still apply for this session.
  }
}

/** The marked clips, in the order they appear in the result. */
export function markedClips(clips: ViralClip[], marks: MarkMap): ViralClip[] {
  return clips.filter((c) => marks[c.id]);
}

/**
 * The title that should be rendered for a clip.
 * Mirrors the backend's own precedence at main.py:2274 and 2463.
 */
export function effectiveTitle(clip: ViralClip, customTitles: Record<string, string>): string {
  return (
    customTitles[clip.id]?.trim() ||
    clip.custom_title?.trim() ||
    clip.title_suggestion?.trim() ||
    clip.title?.trim() ||
    'Clip'
  );
}
