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
  /** No transcript: the render will use Whisper, which the preview cannot run. */
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
        setLoaded((prev) => ({ key, chunks: prev?.chunks ?? [], status: 'error' }));
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
  return { chunks: loaded.chunks, status: loaded.key === key ? loaded.status : 'loading' };
}
