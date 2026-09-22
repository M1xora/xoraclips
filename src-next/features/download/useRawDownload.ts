import { useCallback, useEffect, useRef, useState } from 'react';
import { api, type RawJobStatus } from '../../api/client';
import type { ViralClip } from '../../lib/types';

/**
 * Downloading the untouched video, or one clip of it, without rendering.
 *
 * The backend runs yt-dlp in the background and reports progress through a
 * job id, so this polls rather than streaming. The old frontend had the
 * endpoints wired but no way to reach them.
 */

/** How often to ask the backend how the download is going. */
const POLL_MS = 1000;

export type RawKind = 'video' | 'clip';

export interface RawDownloadState {
  kind: RawKind | null;
  job: RawJobStatus | null;
  error: string | null;
  busy: boolean;
}

export function useRawDownload(onError?: (message: string) => void) {
  const [state, setState] = useState<RawDownloadState>({
    kind: null,
    job: null,
    error: null,
    busy: false,
  });

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const alive = useRef(true);
  // Guards a double click, which would otherwise start two yt-dlp jobs.
  const starting = useRef(false);

  const stop = useCallback(() => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      stop();
    };
  }, [stop]);

  const poll = useCallback(
    (kind: RawKind, jobId: string) => {
      const ask = kind === 'video' ? api.rawDownload.videoStatus : api.rawDownload.clipStatus;

      const tick = async () => {
        if (!alive.current) return;

        try {
          const job = await ask(jobId);
          if (!alive.current) return;

          setState((s) => ({ ...s, job, busy: job.status !== 'ready' && job.status !== 'failed' }));

          if (job.status === 'failed') {
            const msg = job.error || 'Download failed';
            setState((s) => ({ ...s, error: msg, busy: false }));
            onError?.(msg);
            return;
          }

          // 'ready' means the file exists; there is nothing left to poll.
          if (job.status === 'ready') return;

          timer.current = setTimeout(() => void tick(), POLL_MS);
        } catch (err) {
          if (!alive.current) return;
          const msg = err instanceof Error ? err.message : 'Download failed';
          setState((s) => ({ ...s, error: msg, busy: false }));
          onError?.(msg);
        }
      };

      void tick();
    },
    [onError],
  );

  const startVideo = useCallback(
    async (videoUrl: string, videoId: string, title?: string) => {
      if (starting.current) return;
      starting.current = true;
      stop();
      setState({ kind: 'video', job: null, error: null, busy: true });

      try {
        const { job_id } = await api.rawDownload.startVideo({
          video_url: videoUrl,
          video_id: videoId,
          title,
        });
        poll('video', job_id);
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Download failed';
        setState({ kind: 'video', job: null, error: msg, busy: false });
        onError?.(msg);
      } finally {
        starting.current = false;
      }
    },
    [poll, stop, onError],
  );

  const startClip = useCallback(
    async (videoUrl: string, videoId: string, clip: ViralClip, title: string) => {
      if (starting.current) return;
      starting.current = true;
      stop();
      setState({ kind: 'clip', job: null, error: null, busy: true });

      try {
        const { job_id } = await api.rawDownload.startClip({
          video_url: videoUrl,
          video_id: videoId,
          // Trimmed bounds, so the raw clip matches what the trimmer shows.
          start_time: clip.start_time,
          end_time: clip.end_time,
          title,
        });
        poll('clip', job_id);
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Download failed';
        setState({ kind: 'clip', job: null, error: msg, busy: false });
        onError?.(msg);
      } finally {
        starting.current = false;
      }
    },
    [poll, stop, onError],
  );

  const dismiss = useCallback(() => {
    stop();
    setState({ kind: null, job: null, error: null, busy: false });
  }, [stop]);

  return { ...state, startVideo, startClip, dismiss };
}
