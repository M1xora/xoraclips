import { beforeEach, describe, expect, it } from 'vitest';
import { clearApiKey, currentApiKey, loadApiKey, saveApiKey, type KeyStorages } from './apiKeyStore';

const KEY = 'AIzaSyFAKE_USER_KEY_0123456789abcdefgh';

function memoryStorage() {
  const data = new Map<string, string>();
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
    data,
  };
}

let local: ReturnType<typeof memoryStorage>;
let session: ReturnType<typeof memoryStorage>;
let storages: KeyStorages;

beforeEach(() => {
  local = memoryStorage();
  session = memoryStorage();
  storages = { local: () => local, session: () => session };
  clearApiKey(storages);
});

describe('apiKeyStore', () => {
  it('remembers the key across browser restarts when "remember" is on', () => {
    saveApiKey(KEY, true, storages);
    expect(local.data.get('xoraclips_gemini_key')).toBe(KEY);
    expect(session.data.has('xoraclips_gemini_key')).toBe(false);
    expect(loadApiKey(storages)).toEqual({ key: KEY, remember: true });
  });

  it('keeps the key only for this tab when "remember" is off', () => {
    saveApiKey(KEY, false, storages);
    expect(session.data.get('xoraclips_gemini_key')).toBe(KEY);
    expect(local.data.has('xoraclips_gemini_key')).toBe(false);
    expect(loadApiKey(storages)).toEqual({ key: KEY, remember: false });
  });

  it('switching "remember" off moves the key out of long-term storage', () => {
    saveApiKey(KEY, true, storages);
    saveApiKey(KEY, false, storages);
    expect(local.data.has('xoraclips_gemini_key')).toBe(false);
    expect(session.data.get('xoraclips_gemini_key')).toBe(KEY);
  });

  it('"Delete saved key" removes it everywhere', () => {
    saveApiKey(KEY, true, storages);
    session.setItem('xoraclips_gemini_key', KEY);
    clearApiKey(storages);
    expect(local.data.has('xoraclips_gemini_key')).toBe(false);
    expect(session.data.has('xoraclips_gemini_key')).toBe(false);
    expect(currentApiKey()).toBe('');
    expect(loadApiKey(storages).key).toBe('');
  });

  it('an emptied field removes the stored key', () => {
    saveApiKey(KEY, true, storages);
    saveApiKey('', true, storages);
    expect(local.data.has('xoraclips_gemini_key')).toBe(false);
  });

  it('sends the trimmed key', () => {
    saveApiKey(`  ${KEY}\n`, true, storages);
    expect(currentApiKey()).toBe(KEY);
    expect(local.data.get('xoraclips_gemini_key')).toBe(KEY);
  });

  it('keeps working in memory when storage is blocked', () => {
    const blocked: KeyStorages = {
      local: () => {
        throw new DOMException('blocked', 'SecurityError');
      },
      session: () => {
        throw new DOMException('blocked', 'SecurityError');
      },
    };
    expect(() => saveApiKey(KEY, true, blocked)).not.toThrow();
    expect(currentApiKey()).toBe(KEY);
    expect(loadApiKey(blocked)).toEqual({ key: KEY, remember: true });
    expect(() => clearApiKey(blocked)).not.toThrow();
    expect(currentApiKey()).toBe('');
  });
});

describe('old UI slot', () => {
  it('is never written, so the old UI (same origin) cannot pick the key up', () => {
    saveApiKey(KEY, true, storages);
    saveApiKey(KEY, false, storages);
    expect(local.data.has('cheat_clip_gemini_api_key')).toBe(false);
    expect(session.data.has('cheat_clip_gemini_api_key')).toBe(false);
  });

  it('keys left there by older versions are removed on load', () => {
    local.setItem('cheat_clip_gemini_api_key', 'AIzaSyOLD_PLAINTEXT_KEY_FROM_OLD_UI_xx');
    loadApiKey(storages);
    expect(local.data.has('cheat_clip_gemini_api_key')).toBe(false);
  });
});
