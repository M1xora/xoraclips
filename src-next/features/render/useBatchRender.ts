import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api/client';
import type { BatchRenderProgress } from '../../lib/types';

const LAST_BATCH_KEY = 'cheat_clip_last_batch';

type Status = 'idle' | 'starting' | 'running' | 'done' | 'error';

interface State {
  status: Status;
  batchId: string | null;
  progress: BatchRenderProgress | null;
  error: string | null;
  /** True when the stream dropped while the render was still going. */
  lostContact: boolean;
}

const IDLE: State = {
  status: 'idle',
  batchId: null,
  progress: null,
  error: null,
  lostContact: false,
};

/**
 * Starts a batch render and follows its progress stream.
 *
 * Three things the previous implementation got wrong:
 *
 *  - The EventSource was created inside a click handler with no unmount
 *    cleanup, so navigating away left the connection open.
 *
 *  - It closed only on a terminal status. Since the server ends the stream
 *    itself (main.py:2497), a close in cleanup alone would let EventSource
 *    reconnect forever. Both closes are needed, and both are here.
 *
 *  - A dropped connection only reached console.error, so the progress bar
 *    froze with no explanation. Now it surfaces as `lostContact`.
 */
export function useBatchRender(onFinished?: (p: BatchRenderProgress) => void) {
  const [state, setState] = useState<State>(IDLE);
  const sourceRef = useRef<EventSource | null>(null);
  const startingRef = useRef(false);
  const finishedRef = useRef(onFinished);

  useEffect(() => {
    finishedRef.current = onFinished;
  }, [onFinished]);

  const closeStream = useCallback(() => {
    sourceRef.current?.close();
    sourceRef.current = null;
  }, []);

  // Close on unmount, whatever state the render is in.
  useEffect(() => closeStream, [closeStream]);

  const listen = useCallback(
    (batchId: string) => {
      closeStream();
      const source = api.render.progressStream(batchId);
      sourceRef.current = source;

      source.onmessage = (event) => {
        let data: BatchRenderProgress;
        try {
          data = JSON.parse(event.data) as BatchRenderProgress;
        } catch {
          return; // Ignore one malformed frame.
        }

        setState((s) => ({ ...s, progress: data, lostContact: false }));

        if (data.overall_status === 'completed' || data.overall_status === 'error') {
          // Close here as well as in cleanup: the server ends the stream on
          // its own, and a normal close makes EventSource reconnect.
          closeStream();
          setState((s) => ({
            ...s,
            status: data.overall_status === 'error' ? 'error' : 'done',
            error: data.error_message ?? null,
          }));
          finishedRef.current?.(data);
          try {
            localStorage.removeItem(LAST_BATCH_KEY);
          } catch {
            // Nothing to clean up if storage is unavailable.
          }
        }
      };

      source.onerror = () => {
        closeStream();
        // EventSource cannot read the HTTP status, so a stopped backend and
        // a batch the server has forgotten look identical from here.
        setState((s) =>
          s.status === 'running' ? { ...s, lostContact: true } : s,
        );
      };
    },
    [closeStream],
  );

  const start = useCallback(
    async (payload: unknown) => {
      // A second click would start a second batch with its own stream.
      if (startingRef.current) return null;
      startingRef.current = true;

      setState({ ...IDLE, status: 'starting' });

      try {
        const { batch_id, total_clips } = await api.render.startBatch(payload);

        // Keep the id so the results survive closing the tab: the backend
        // carries on rendering without the client (main.py:2482).
        try {
          localStorage.setItem(LAST_BATCH_KEY, batch_id);
        } catch {
          // Not fatal.
        }

        setState({
          status: 'running',
          batchId: batch_id,
          progress: {
            batch_id,
            total_clips,
            current_clip_index: 0,
            overall_status: 'running',
            clips: [],
          },
          error: null,
          lostContact: false,
        });

        listen(batch_id);
        return batch_id;
      } catch (err) {
        setState({
          ...IDLE,
          status: 'error',
          error: err instanceof Error ? err.message : 'Could not start the render',
        });
        return null;
      } finally {
        startingRef.current = false;
      }
    },
    [listen],
  );

  /** Reattaches to a batch, after a dropped stream or a reopened tab. */
  const reconnect = useCallback(
    (batchId?: string) => {
      const id = batchId ?? state.batchId ?? readLastBatchId();
      if (!id) return;
      setState((s) => ({ ...s, status: 'running', batchId: id, lostContact: false }));
      listen(id);
    },
    [listen, state.batchId],
  );

  const dismiss = useCallback(() => {
    closeStream();
    setState(IDLE);
    try {
      localStorage.removeItem(LAST_BATCH_KEY);
    } catch {
      // Ignore.
    }
  }, [closeStream]);

  return { ...state, start, reconnect, dismiss };
}

/** The last batch this browser started, if any. */
export function readLastBatchId(): string | null {
  try {
    return localStorage.getItem(LAST_BATCH_KEY);
  } catch {
    return null;
  }
}
