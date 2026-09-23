import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  CAPTION_DEBOUNCE_MS,
  CAPTION_MAX_RETRIES,
  CAPTION_RETRY_MS,
  captionQueryKey,
  createCaptionCache,
  createCaptionLoader,
  type CaptionFetcher,
  type CaptionLoadResult,
  type CaptionQuery,
} from './captionLoader';
import type { CaptionChunksResponse } from '../../api/client';
import type { TranscriptLine } from '../../lib/types';

const transcript: TranscriptLine[] = [{ start: 10, end: 14, text: 'halo semua' }];

function query(clipStart: number, clipEnd = 20): CaptionQuery {
  return { transcript, clipStart, clipEnd, textCase: 'uppercase' };
}

function response(tag: string): CaptionChunksResponse {
  return {
    source: 'transcript',
    chunks: [{ start: 0, end: 1, text: tag, words: [{ text: tag, start: 0, end: 1 }] }],
  };
}

describe('createCaptionLoader', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('sends one request after a burst of trim changes', async () => {
    const fetcher = vi.fn<CaptionFetcher>(async (body) => response(String(body.clip_start)));
    const loader = createCaptionLoader(fetcher, createCaptionCache());
    const results: CaptionLoadResult[] = [];

    for (const start of [10, 10.5, 11, 11.5, 12]) {
      loader.load(query(start), (r) => results.push(r));
      await vi.advanceTimersByTimeAsync(50);
    }
    expect(fetcher).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(CAPTION_DEBOUNCE_MS);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls[0][0]).toMatchObject({ clip_start: 12, clip_end: 20, text_case: 'uppercase' });
    expect(results).toEqual([{ status: 'ready', response: response('12') }]);
  });

  it('drops the answer to a request that a newer trim replaced', async () => {
    let resolveSlow: (r: CaptionChunksResponse) => void = () => {};
    const signals: AbortSignal[] = [];
    const fetcher = vi.fn<CaptionFetcher>((body, signal) => {
      signals.push(signal);
      if (body.clip_start === 10) return new Promise((r) => (resolveSlow = r));
      return Promise.resolve(response('new'));
    });
    const loader = createCaptionLoader(fetcher, createCaptionCache());
    const results: CaptionLoadResult[] = [];

    loader.load(query(10), (r) => results.push(r));
    await vi.advanceTimersByTimeAsync(CAPTION_DEBOUNCE_MS);
    loader.load(query(11), (r) => results.push(r));
    await vi.advanceTimersByTimeAsync(CAPTION_DEBOUNCE_MS);

    resolveSlow(response('old'));
    await vi.runAllTimersAsync();

    expect(signals[0].aborted).toBe(true);
    expect(results).toEqual([{ status: 'ready', response: response('new') }]);
  });

  it('answers from the cache without asking again', async () => {
    const fetcher = vi.fn<CaptionFetcher>(async () => response('x'));
    const cache = createCaptionCache();
    const loader = createCaptionLoader(fetcher, cache);

    loader.load(query(10), () => {});
    await vi.advanceTimersByTimeAsync(CAPTION_DEBOUNCE_MS);

    const results: CaptionLoadResult[] = [];
    loader.load(query(10), (r) => results.push(r));
    expect(results).toEqual([{ status: 'ready', response: response('x') }]);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('reports an error when the backend cannot be reached', async () => {
    const loader = createCaptionLoader(
      vi.fn<CaptionFetcher>(async () => {
        throw new Error('offline');
      }),
      createCaptionCache(),
    );
    const results: CaptionLoadResult[] = [];
    loader.load(query(10), (r) => results.push(r));
    await vi.advanceTimersByTimeAsync(CAPTION_DEBOUNCE_MS);
    expect(results).toEqual([{ status: 'error' }]);
  });

  it('keeps retrying until the backend answers', async () => {
    let calls = 0;
    const fetcher = vi.fn<CaptionFetcher>(async () => {
      calls += 1;
      if (calls < 3) throw new Error('backend still starting');
      return response('late');
    });
    const loader = createCaptionLoader(fetcher, createCaptionCache());
    const results: CaptionLoadResult[] = [];

    loader.load(query(10), (r) => results.push(r));
    await vi.advanceTimersByTimeAsync(CAPTION_DEBOUNCE_MS);
    await vi.advanceTimersByTimeAsync(CAPTION_RETRY_MS * 2);

    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(results).toEqual([
      { status: 'error' },
      { status: 'error' },
      { status: 'ready', response: response('late') },
    ]);
  });

  it('gives up after the retry limit', async () => {
    const fetcher = vi.fn<CaptionFetcher>(async () => {
      throw new Error('offline');
    });
    const loader = createCaptionLoader(fetcher, createCaptionCache());
    loader.load(query(10), () => {});
    await vi.advanceTimersByTimeAsync(CAPTION_DEBOUNCE_MS + CAPTION_RETRY_MS * (CAPTION_MAX_RETRIES + 3));
    expect(fetcher).toHaveBeenCalledTimes(1 + CAPTION_MAX_RETRIES);
  });

  it('stops retrying once a new trim replaces the request', async () => {
    const fetcher = vi.fn<CaptionFetcher>(async (body) => {
      if (body.clip_start === 10) throw new Error('offline');
      return response('new');
    });
    const loader = createCaptionLoader(fetcher, createCaptionCache());
    loader.load(query(10), () => {});
    await vi.advanceTimersByTimeAsync(CAPTION_DEBOUNCE_MS);
    loader.load(query(11), () => {});
    await vi.advanceTimersByTimeAsync(CAPTION_RETRY_MS * 5);
    expect(fetcher.mock.calls.filter(([b]) => b.clip_start === 10)).toHaveLength(1);
  });

  it('cancel stops a pending request', async () => {
    const fetcher = vi.fn<CaptionFetcher>(async () => response('x'));
    const loader = createCaptionLoader(fetcher, createCaptionCache());
    loader.load(query(10), () => {});
    loader.cancel();
    await vi.advanceTimersByTimeAsync(CAPTION_DEBOUNCE_MS * 2);
    expect(fetcher).not.toHaveBeenCalled();
  });
});

describe('captionQueryKey', () => {
  it('changes with every input the backend uses', () => {
    const base = captionQueryKey(query(10));
    expect(captionQueryKey(query(11))).not.toBe(base);
    expect(captionQueryKey(query(10, 21))).not.toBe(base);
    expect(captionQueryKey({ ...query(10), textCase: 'lowercase' })).not.toBe(base);
    expect(captionQueryKey({ ...query(10), transcript: [...transcript] })).not.toBe(base);
    expect(captionQueryKey(query(10))).toBe(base);
  });
});
