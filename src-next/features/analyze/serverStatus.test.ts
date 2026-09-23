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
      // longer identifier such as the storage slot `cheat_clip_gemini_api_key`.
      .filter(([, text]) => /(^|[^\w])api_key\b/m.test(text))
      .map(([path]) => path);
    expect(offenders).toEqual([]);
  });
});
