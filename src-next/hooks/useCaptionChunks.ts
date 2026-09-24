import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import {
  captionQueryKey,
  createCaptionCache,
  createCaptionLoader,
} from '../features/studio/captionLoader';
import { chunksFromApi, type CaptionChunk } from '../features/studio/captions';
import type { TextCaseOption, TranscriptLine } from '../lib/types';

const sharedCache = createCaptionCache();

export type CaptionChunksStatus =
  | 'off'
  | 'loading'
  | 'ready'
  /**
   * No transcript words for this clip (no transcript at all, or none in this
   * stretch): the render falls back to Whisper, which the preview cannot run.
   */
  | 'renderOnly'
  | 'error';

interface Loaded {
  key: string;
  chunks: CaptionChunk[];
  status: 'ready' | 'renderOnly' | 'error';
}

/**
 * Caption chunks for the clip being previewed, fetched from the backend so
 * they match the export exactly. While a new trim is loading, the previous
 * chunks stay on screen instead of blinking out.
 */
export function useCaptionChunks(
  transcript: TranscriptLine[] | undefined,
  clipStart: number,
  clipEnd: number,
  textCase: TextCaseOption,
  enabled: boolean,
): { chunks: CaptionChunk[]; status: CaptionChunksStatus } {
  const loader = useMemo(() => createCaptionLoader(api.captionChunks, sharedCache), []);
  const [loaded, setLoaded] = useState<Loaded | null>(null);

  const active = enabled && !!transcript && transcript.length > 0;
  const key = active ? captionQueryKey({ transcript, clipStart, clipEnd, textCase }) : null;

  useEffect(() => {
    if (!active || !transcript || key === null) return;
    loader.load({ transcript, clipStart, clipEnd, textCase }, (result) => {
      if (result.status === 'error') {
        // Never show chunks from a different trim; the loader keeps retrying.
        setLoaded({ key, chunks: [], status: 'error' });
        return;
      }
      const { chunks, source } = result.response;
      setLoaded({
        key,
        chunks: chunksFromApi(chunks, clipStart),
        status: source === 'none' ? 'renderOnly' : 'ready',
      });
    });
    return () => loader.cancel();
  }, [loader, active, key, transcript, clipStart, clipEnd, textCase]);

  if (!enabled) return { chunks: [], status: 'off' };
  if (!active) return { chunks: [], status: 'renderOnly' };
  if (!loaded) return { chunks: [], status: 'loading' };
  // Chunks of another clip or trim are never shown while these load: the
  // preview player is reused per clip now (#40).
  if (loaded.key !== key) return { chunks: [], status: 'loading' };
  return { chunks: loaded.chunks, status: loaded.status };
}
