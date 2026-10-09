import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { whisperMissing } from '../features/analyze/serverStatus';

/**
 * Whether the Studio should say that automatic subtitles are missing (#112).
 *
 * Whisper is an optional install: it pulls torch and friends, ~737 MB, and
 * only ever runs as a fallback for videos YouTube has no transcript for.
 * Without this check a clip from such a video would come back with no
 * subtitles and no explanation, which reads like a broken app.
 *
 * Stays `false` while loading and when the backend cannot be reached: a
 * warning shown on a guess is worse than none.
 */
export function useWhisperMissing(): boolean {
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    api
      .health(controller.signal)
      .then((health) => {
        if (!controller.signal.aborted) setMissing(whisperMissing(health));
      })
      .catch(() => {
        // Unreachable backend is not the same as Whisper being absent.
      });
    return () => controller.abort();
  }, []);

  return missing;
}
