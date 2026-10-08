import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../../api/client';
import type { BatchRenderProgress } from '../../lib/types';

const LAST_BATCH_KEY = 'xoraclips_last_batch';

type Status = 'idle' | 'starting' | 'running' | 'done' | 'error';

interface State {
  status: Status;
  batchId: string | null;
  progress: BatchRenderProgress | null;
  error: string | null;
  /** True when the stream dropped while the render was still going. */
  lostContact: boolean;
}

/**
 * What to do with a stored batch id after asking the backend about it (#107).
 *
 * Pulled out of the effect so the rule can be tested on its own, because the
 * dangerous case is silent: treating an unreachable backend like a 404 drops
 * the id, and the render it pointed at is then lost for good even though it
 * is still running.
 */
export function recoveryAction(
  error: unknown,
): 'forget' | 'keep' {
  return error instanceof ApiError && error.status === 404 ? 'forget' : 'keep';
}

/** Drop the stored batch id. One place, so "when is it safe to forget?" has
 *  one answer: only when the backend itself said the batch is gone (#107). */
function forget(): void {
  try {
    localStorage.removeItem(LAST_BATCH_KEY);
  } catch {
    // Storage can be unavailable; nothing to clean up then.
  }
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
  /**
   * Set the moment the user starts a render, so the recovery check from the
   * page load can never write over it (#107). Without this, a status reply
   * that lands after the click would restore the OLD batch id and close the
   * new render's stream.
   */
  const supersededRef = useRef(false);
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
          forget();
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
      supersededRef.current = true;   // Anything the page load was recovering is now stale.

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

  /**
   * Picks up a render the browser was watching before it was reloaded (#107).
   *
   * Runs once. The backend keeps rendering whether or not anything is
   * watching, so after a refresh the id in storage is the only thread back to
   * it, and nothing used to pull that thread.
   *
   * The three answers are kept apart on purpose. A 404 means the backend is
   * running and does not know this batch, so the id is dead and is dropped.
   * Any other failure means the backend could not be reached, and the id is
   * KEPT: the render may well still be there once it is back up, and throwing
   * the id away would lose it for good.
   */
  useEffect(() => {
    const id = readLastBatchId();
    if (!id) return;

    const controller = new AbortController();
    let cancelled = false;

    api.render
      .status(id, controller.signal)
      .then((batch) => {
        if (cancelled || supersededRef.current) return;
        if (batch.overall_status === 'running') {
          setState({ status: 'running', batchId: id, progress: batch, error: null, lostContact: false });
          listen(id);
          return;
        }
        // Already finished while nobody was looking: show the result, with
        // its download links, instead of an empty queue.
        setState({
          status: batch.overall_status === 'error' ? 'error' : 'done',
          batchId: id,
          progress: batch,
          error: batch.error_message ?? null,
          lostContact: false,
        });
        forget();
      })
      .catch((err: unknown) => {
        if (cancelled || supersededRef.current) return;
        if (recoveryAction(err) === 'forget') {
          forget();   // The backend answered: this batch is gone.
          return;
        }
        // Could not reach the backend. Say so, and keep the id — but leave
        // status 'idle' and batchId null, so nothing downstream treats this
        // as a render it can follow. The id stays in storage, and the next
        // page load retries it; reconnect() would only spin on a dead id.
        setState((st) => ({ ...st, lostContact: true }));
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
    // Once, on mount: this is about what was left behind, not about state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const dismiss = useCallback(() => {
    closeStream();
    setState(IDLE);
    forget();
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
