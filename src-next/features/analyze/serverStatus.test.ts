import { afterEach, describe, expect, it, vi } from 'vitest';
import { aiStatusFromHealth } from './serverStatus';
import { analyzeErrorView } from './analyzeErrors';
import { api, ApiError, GEMINI_KEY_HEADER } from '../../api/client';
import { buildAnalyzeInit } from '../../hooks/useAnalyze';
import { id } from '../../i18n/id';

const KEY = 'AIzaSyFAKE_USER_KEY_0123456789abcdefgh';

describe('aiStatusFromHealth', () => {
  it('only mock mode changes the form', () => {
    expect(aiStatusFromHealth({ mock_mode: true })).toBe('mock');
    expect(aiStatusFromHealth({ mock_mode: false })).toBe('normal');
    expect(aiStatusFromHealth({})).toBe('normal');
  });

  it('does not block the form when the backend cannot be reached', () => {
    expect(aiStatusFromHealth(null)).toBe('unknown');
  });
});

describe('the key travels only in a header', () => {
  afterEach(() => vi.unstubAllGlobals());

  function stubFetch(response: Response) {
    const fetchMock = vi.fn(async () => response);
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
  }

  it('model list: header, never the URL', async () => {
    const fetchMock = stubFetch(new Response(JSON.stringify({ models: ['m'] })));
    await api.listModels(`  ${KEY}  `);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/models');
    expect(init.headers).toEqual({ [GEMINI_KEY_HEADER]: KEY });
  });

  it('model list without a key sends no key header', async () => {
    const fetchMock = stubFetch(new Response(JSON.stringify({ models: [] })));
    await api.listModels('   ');
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.headers).toEqual({});
  });

  it('analysis: header, never the body', () => {
    const init = buildAnalyzeInit({ url: 'https://youtu.be/x', duration: '30s' }, KEY);
    expect((init.headers as Record<string, string>)[GEMINI_KEY_HEADER]).toBe(KEY);
    expect(String(init.body)).not.toContain(KEY);
    expect(JSON.parse(String(init.body))).toEqual({ url: 'https://youtu.be/x', duration: '30s' });
  });

  it('a rejected key comes back as ApiError with its code', async () => {
    stubFetch(
      new Response(JSON.stringify({ detail: { code: 'key_invalid', message: 'Google rejected your key' } }), {
        status: 401,
      }),
    );
    const err = await api.listModels(KEY).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe('key_invalid');
    expect(err.status).toBe(401);
    expect(err.message).toBe('Google rejected your key');
  });
});

describe('analyzeErrorView', () => {
  it.each([
    ['key_missing', id.errors.keyMissing, true],
    ['key_invalid', id.errors.keyInvalid, true],
    ['key_quota', id.errors.keyQuota, true],
    ['region_unsupported', id.errors.regionUnsupported, false],
    ['model_unavailable', id.errors.modelUnavailable, false],
    ['ai_busy', id.errors.aiBusy, false],
    ['ai_failed', id.errors.aiFailed, false],
  ])('%s', (code, message, keyProblem) => {
    expect(analyzeErrorView(code, 'raw', id)).toEqual({ message, keyProblem });
  });

  it('shows the server text for non-AI failures', () => {
    expect(analyzeErrorView(null, 'Invalid YouTube URL.', id)).toEqual({
      message: 'Invalid YouTube URL.',
      keyProblem: false,
    });
  });

  it('tells the user a busy service is not their key', () => {
    expect(id.errors.aiBusy).toMatch(/tidak bermasalah/);
  });

  // Issue #9: caption failures are one short line, never the server's tier dump.
  it.each([
    ['captions_disabled', id.errors.captionsDisabled],
    ['video_unavailable', id.errors.videoUnavailable],
    ['age_restricted', id.errors.ageRestricted],
    ['video_live', id.errors.videoLive],
    ['captions_unavailable', id.errors.captionsUnavailable],
  ])('%s', (code, message) => {
    expect(analyzeErrorView(code, 'Tier 5 (Direct Python API): ...', id)).toEqual({ message, keyProblem: false });
  });

  it('a YouTube block says when to try again', () => {
    const now = new Date(2026, 8, 23, 14, 25, 0).getTime();
    const view = analyzeErrorView('youtube_blocked', 'raw', id, {
      retryAt: now + 600_000,
      now,
      locale: 'id-ID',
    });
    expect(view.keyProblem).toBe(false);
    expect(view.message).toMatch(/membatasi akses/);
    expect(view.message).toMatch(/14[.:]35/);
    expect(view.message).toMatch(/sekitar 10 menit lagi/);
    expect(view.message).toMatch(/upload subtitle manual/);
  });

  it('a YouTube block without a time still gives advice', () => {
    expect(analyzeErrorView('youtube_blocked', 'raw', id).message).toBe(id.errors.youtubeBlockedLater);
    const now = Date.now();
    expect(analyzeErrorView('youtube_blocked', 'raw', id, { retryAt: now - 1, now }).message).toBe(
      id.errors.youtubeBlockedLater,
    );
  });
});

describe('no key in a URL or a request body', () => {
  // Every source file, as text: guards against the old `?api_key=` URL
  // parameter or `api_key` body field coming back (issues #8, #12).
  const sources = import.meta.glob(['../../**/*.{ts,tsx}', '!../../**/*.test.{ts,tsx}'], {
    query: '?raw',
    import: 'default',
    eager: true,
  }) as Record<string, string>;

  it('covers the source tree', () => {
    expect(Object.keys(sources).length).toBeGreaterThan(30);
  });

  it('never uses the api_key parameter name', () => {
    const offenders = Object.entries(sources)
      // `api_key` as its own name (`?api_key=`, `api_key:`), not inside a
      // longer identifier such as the storage slot `xoraclips_gemini_api_key`.
      .filter(([, text]) => /(^|[^\w])api_key\b/m.test(text))
      .map(([path]) => path);
    expect(offenders).toEqual([]);
  });
});

describe('validation errors (422)', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('show the reason, not only the status', async () => {
    const body = { detail: [{ loc: ['body'], msg: 'Value error, end_time must be greater than start_time' }] };
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(body), { status: 422 })));
    const err = await api.rawDownload
      .startClip({ video_id: 'p1t-074cn38', start_time: 9, end_time: 4, title: 'x' })
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).message).toBe('end_time must be greater than start_time');
  });
});
