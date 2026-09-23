import { useCallback, useRef, useState } from 'react';
import type { AnalyzeResponse } from '../lib/types';
import { geminiKeyHeaders } from '../api/client';

export interface AnalyzeProgress {
  step: number;
  stepProgress: number;
  overallProgress: number;
  stage: string;
  detail: string;
}

export interface AnalyzeRequest {
  url: string;
  duration: string;
  model?: string;
  custom_prompt?: string;
  range_start?: number;
  range_end?: number;
  subtitles?: string;
  subtitles_filename?: string;
  target_clip_count?: number;
}

type Status = 'idle' | 'running' | 'done' | 'error';

/** An analysis failure with the backend's error code (e.g. `key_invalid`), when it sent one. */
export class AnalyzeError extends Error {
  readonly code?: string;

  constructor(message: string, code?: string) {
    super(message);
    this.name = 'AnalyzeError';
    this.code = code;
  }
}

/**
 * The fetch options for /api/analyze. The key travels only in the
 * X-Gemini-Api-Key header, never in the body or the URL (issue #12).
 */
export function buildAnalyzeInit(
  payload: AnalyzeRequest,
  apiKey: string | undefined,
  signal?: AbortSignal,
): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...geminiKeyHeaders(apiKey) },
    body: JSON.stringify(payload),
    signal,
  };
}

const EMPTY_PROGRESS: AnalyzeProgress = {
  step: 0,
  stepProgress: 0,
  overallProgress: 0,
  stage: '',
  detail: '',
};

/**
 * Drives POST /api/analyze, which replies with a Server-Sent Events stream.
 *
 * Two bugs from the previous implementation are fixed here:
 *  - `response.ok` is checked before reading the stream. Previously a 4xx/5xx
 *    still had a body, so it was parsed as SSE, produced no events, and was
 *    reported as "connection closed" instead of the real backend error.
 *  - The request is abortable, so navigating away or starting a second
 *    analysis cancels the first instead of leaving it writing to state.
 */
export function useAnalyze() {
  const [status, setStatus] = useState<Status>('idle');
  const [progress, setProgress] = useState<AnalyzeProgress>(EMPTY_PROGRESS);
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setStatus('idle');
  }, []);

  const analyze = useCallback(async (payload: AnalyzeRequest, apiKey?: string) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setStatus('running');
    setProgress(EMPTY_PROGRESS);
    setResult(null);
    setError(null);
    setErrorCode(null);

    try {
      const res = await fetch('/api/analyze', buildAnalyzeInit(payload, apiKey, controller.signal));

      // Check the status BEFORE treating the body as an event stream.
      if (!res.ok) {
        let detail = `Analysis failed (HTTP ${res.status})`;
        try {
          const body = await res.json();
          if (typeof body?.detail === 'string') detail = body.detail;
        } catch {
          // Not JSON - keep the status message.
        }
        throw new Error(detail);
      }

      if (!res.body) throw new Error('Server sent no response stream.');

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let finalResult: AnalyzeResponse | null = null;

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // SSE frames are separated by a blank line.
        const frames = buffer.split('\n\n');
        buffer = frames.pop() ?? '';

        for (const frame of frames) {
          const line = frame.split('\n').find((l) => l.startsWith('data:'));
          if (!line) continue;

          let event: Record<string, unknown>;
          try {
            event = JSON.parse(line.slice(5).trim());
          } catch {
            continue; // Ignore a malformed frame rather than failing the run.
          }

          if (typeof event.error === 'string') {
            throw new AnalyzeError(event.error, typeof event.code === 'string' ? event.code : undefined);
          }

          if (event.result) {
            finalResult = event.result as AnalyzeResponse;
            continue;
          }

          setProgress({
            step: Number(event.step ?? 0),
            stepProgress: Number(event.step_progress ?? 0),
            overallProgress: Number(event.overall_progress ?? 0),
            stage: String(event.stage ?? ''),
            detail: String(event.detail ?? event.message ?? ''),
          });
        }
      }

      if (!finalResult) throw new Error('Analysis ended before returning a result.');

      setResult(finalResult);
      setStatus('done');
      return finalResult;
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return null;
      setError(err instanceof Error ? err.message : 'Unexpected error during analysis.');
      setErrorCode(err instanceof AnalyzeError ? (err.code ?? null) : null);
      setStatus('error');
      return null;
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
    }
  }, []);

  return { analyze, cancel, status, progress, result, error, errorCode, setResult };
}
