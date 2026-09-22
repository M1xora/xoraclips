import type { AnalyzeResponse } from '../../lib/types';
import { withClipIds } from '../clips/clipIdentity';
import type { AnalyzeRequest } from '../../hooks/useAnalyze';

/**
 * Caches analysis results in localStorage.
 *
 * This is not a convenience. Re-analysing a video calls Gemini again and
 * spends the user's quota, which is why the previous code cached too
 * (App.tsx:861, "avoid redundant API/Gemini processing"). The key includes
 * every input that changes the result, so changing any setting re-analyses.
 */

const CACHE_PREFIX = 'cheat_clip_cache_';
const TIME_PREFIX = 'cheat_clip_ts_';

/** Trims a value into something safe to embed in a storage key. */
function slug(value: string, max = 24): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').slice(0, max);
}

/**
 * Builds the cache key. Mirrors the previous scheme so results cached by the
 * old frontend are still found.
 */
export function cacheKey(videoId: string, req: AnalyzeRequest): string | null {
  if (!videoId) return null;

  let key = `${CACHE_PREFIX}${videoId}_${req.duration}`;
  key += `_model_${req.model ?? 'default'}`;
  key += `_clips_${req.target_clip_count ?? 'auto'}`;
  if (req.custom_prompt) key += `_prompt_${slug(req.custom_prompt)}`;
  if (req.range_start !== undefined && req.range_end !== undefined) {
    key += `_range_${req.range_start}_${req.range_end}`;
  }
  if (req.subtitles) key += '_manual';

  return key;
}

function timeKey(key: string): string {
  return key.replace(CACHE_PREFIX, TIME_PREFIX);
}

/** Returns a cached result, or null. Ids are backfilled for old entries. */
export function readCache(key: string | null): AnalyzeResponse | null {
  if (!key) return null;
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as AnalyzeResponse;
    if (!parsed?.clips || !Array.isArray(parsed.clips)) return null;
    return withClipIds(parsed);
  } catch {
    return null;
  }
}

export function writeCache(key: string | null, result: AnalyzeResponse): void {
  if (!key) return;
  try {
    localStorage.setItem(key, JSON.stringify(result));
    localStorage.setItem(timeKey(key), new Date().toISOString());
  } catch {
    // Quota exceeded, common on mobile Safari. The app works uncached.
  }
}

/**
 * Re-saves a result whose clips changed, for example after a trim.
 * Without this, trims are lost on refresh.
 */
export function updateCachedResult(key: string | null, result: AnalyzeResponse): void {
  if (!key) return;
  try {
    if (localStorage.getItem(key)) writeCache(key, result);
  } catch {
    // Nothing to update if storage is unavailable.
  }
}

export interface HistoryEntry {
  /** The localStorage key, which is also what readCache takes. */
  key: string;
  videoId: string;
  title: string;
  clipCount: number;
  /** When the analysis was cached, or null for entries written before
      timestamps were recorded. */
  savedAt: string | null;
}

/**
 * Every analysis still in the cache, newest first.
 *
 * Nothing extra is stored for this: the cache already holds each result and
 * the time it was written, so history is a read over what is there. An entry
 * that fails to parse is skipped rather than breaking the list.
 */
export function listHistory(): HistoryEntry[] {
  const out: HistoryEntry[] = [];

  try {
    for (let i = 0; i < localStorage.length; i += 1) {
      const key = localStorage.key(i);
      if (!key || !key.startsWith(CACHE_PREFIX)) continue;

      try {
        const raw = localStorage.getItem(key);
        if (!raw) continue;

        const parsed = JSON.parse(raw) as AnalyzeResponse;
        if (!parsed?.clips || !Array.isArray(parsed.clips)) continue;

        out.push({
          key,
          videoId: parsed.video_id,
          title: parsed.title || parsed.video_id,
          clipCount: parsed.clips.length,
          savedAt: localStorage.getItem(timeKey(key)),
        });
      } catch {
        // A corrupt entry should not hide the rest of the history.
      }
    }
  } catch {
    // localStorage can throw outright in private mode.
    return [];
  }

  return out.sort((a, b) => (b.savedAt ?? '').localeCompare(a.savedAt ?? ''));
}

/** Drops one analysis from the cache, freeing its quota. */
export function removeFromHistory(key: string): void {
  try {
    localStorage.removeItem(key);
    localStorage.removeItem(timeKey(key));
  } catch {
    // Nothing to remove if storage is unavailable.
  }
}
