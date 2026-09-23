import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  aiStatusFromHealth,
  LEGACY_API_KEY_STORAGE,
  purgeLegacyApiKey,
} from './serverStatus';
import { api } from '../../api/client';

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (k: string) => data.get(k) ?? null,
    removeItem: (k: string) => void data.delete(k),
    data,
  };
}

describe('purgeLegacyApiKey', () => {
  it('removes a key an older version left in the browser', () => {
    const storage = memoryStorage({ [LEGACY_API_KEY_STORAGE]: 'AIzaSyOLD', other: 'keep' });
    expect(purgeLegacyApiKey(() => storage)).toBe(true);
    expect(storage.data.has(LEGACY_API_KEY_STORAGE)).toBe(false);
    expect(storage.data.get('other')).toBe('keep');
  });

  it('does nothing when there is no old key', () => {
    expect(purgeLegacyApiKey(() => memoryStorage())).toBe(false);
  });

  it('never throws when storage is blocked', () => {
    expect(
      purgeLegacyApiKey(() => {
        throw new DOMException('blocked', 'SecurityError');
      }),
    ).toBe(false);
    expect(purgeLegacyApiKey(() => undefined)).toBe(false);
  });
});

describe('aiStatusFromHealth', () => {
  it('maps the server configuration to what the form shows', () => {
    expect(aiStatusFromHealth({ gemini_env_configured: true, mock_mode: false })).toBe('ready');
    expect(aiStatusFromHealth({ gemini_env_configured: false, mock_mode: false })).toBe('notConfigured');
    expect(aiStatusFromHealth({ gemini_env_configured: false, mock_mode: true })).toBe('mock');
    expect(aiStatusFromHealth({ gemini_env_configured: true, mock_mode: true })).toBe('mock');
    expect(aiStatusFromHealth({})).toBe('notConfigured');
  });

  it('does not block the form when the backend cannot be reached', () => {
    expect(aiStatusFromHealth(null)).toBe('unknown');
  });
});

describe('api client', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('asks for the model list without any key', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ models: ['m'] })));
    vi.stubGlobal('fetch', fetchMock);
    await api.listModels();
    const [url] = fetchMock.mock.calls[0] as unknown as [string];
    expect(url).toBe('/api/models');
  });
});

describe('no API key leaves the browser', () => {
  // Every source file, as text. Guards against a key field or parameter
  // creeping back in (issue #8).
  const sources = import.meta.glob(['../../**/*.{ts,tsx}', '!../../**/*.test.{ts,tsx}'], {
    query: '?raw',
    import: 'default',
    eager: true,
  }) as Record<string, string>;

  it('covers the source tree', () => {
    expect(Object.keys(sources).length).toBeGreaterThan(30);
  });

  it('never sends or asks for api_key', () => {
    const offenders = Object.entries(sources)
      .filter(([path]) => !path.endsWith('/serverStatus.ts'))
      // Whole identifiers only: api_key, apiKey, api-key (not purgeLegacyApiKey).
      .filter(([, text]) => /\bapi[_-]?key\b/i.test(text))
      .map(([path]) => path);
    expect(offenders).toEqual([]);
  });
});
