import type { CaptionChunksRequest, CaptionChunksResponse } from '../../api/client';
import type { TextCaseOption, TranscriptLine } from '../../lib/types';

export type CaptionFetcher = (
  body: CaptionChunksRequest,
  signal: AbortSignal,
) => Promise<CaptionChunksResponse>;

export type CaptionLoadResult =
  | { status: 'ready'; response: CaptionChunksResponse }
  | { status: 'error' };

export interface CaptionQuery {
  transcript: TranscriptLine[];
  clipStart: number;
  clipEnd: number;
  textCase: TextCaseOption;
}

/** Wait before asking, so dragging a trim handle sends one request, not dozens. */
export const CAPTION_DEBOUNCE_MS = 150;
const MAX_CACHE_ENTRIES = 50;

// Transcripts are large; key them by identity instead of by content. The
// analysis result keeps the same array for the whole session.
const transcriptIds = new WeakMap<TranscriptLine[], number>();
let nextTranscriptId = 1;

function transcriptId(transcript: TranscriptLine[]): number {
  let id = transcriptIds.get(transcript);
  if (id === undefined) {
    id = nextTranscriptId++;
    transcriptIds.set(transcript, id);
  }
  return id;
}

export function captionQueryKey(q: CaptionQuery): string {
  return `${transcriptId(q.transcript)}|${q.clipStart}|${q.clipEnd}|${q.textCase}`;
}

/** Shared across previews so switching back to a clip needs no request. */
export type CaptionCache = Map<string, CaptionChunksResponse>;

export function createCaptionCache(): CaptionCache {
  return new Map();
}

/**
 * Loads caption chunks for the preview: debounced, cached, and with any
 * superseded request aborted so a slow answer for an old trim can never
 * overwrite the current one.
 */
export function createCaptionLoader(
  fetcher: CaptionFetcher,
  cache: CaptionCache,
  debounceMs = CAPTION_DEBOUNCE_MS,
) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let controller: AbortController | undefined;

  function cancel() {
    if (timer !== undefined) clearTimeout(timer);
    timer = undefined;
    controller?.abort();
    controller = undefined;
  }

  function load(query: CaptionQuery, onResult: (result: CaptionLoadResult) => void) {
    cancel();

    const key = captionQueryKey(query);
    const hit = cache.get(key);
    if (hit) {
      onResult({ status: 'ready', response: hit });
      return;
    }

    timer = setTimeout(() => {
      timer = undefined;
      const current = new AbortController();
      controller = current;
      const body: CaptionChunksRequest = {
        transcript: query.transcript,
        clip_start: query.clipStart,
        clip_end: query.clipEnd,
        text_case: query.textCase,
      };
      fetcher(body, current.signal)
        .then((response) => {
          cache.set(key, response);
          if (cache.size > MAX_CACHE_ENTRIES) {
            // Maps iterate in insertion order: drop the oldest entry.
            cache.delete(cache.keys().next().value as string);
          }
          if (!current.signal.aborted) onResult({ status: 'ready', response });
        })
        .catch(() => {
          if (!current.signal.aborted) onResult({ status: 'error' });
        });
    }, debounceMs);
  }

  return { load, cancel };
}
