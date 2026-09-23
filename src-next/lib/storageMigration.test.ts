import { describe, expect, it } from 'vitest';
import { migrateStorage } from './storageMigration';

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    get length() {
      return data.size;
    },
    key: (i: number) => [...data.keys()][i] ?? null,
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
    data,
  };
}

describe('migrateStorage (issue #14 rename)', () => {
  it('moves settings, history and cache to the new names', () => {
    const s = memoryStorage({
      cheat_clip_theme: 'dark',
      cheat_clip_language: 'id',
      cheat_clip_selected_model: 'gemini-2.5-flash',
      cheat_clip_cache_abc_short: '{"clips":[]}',
      cheat_clip_ts_abc_short: '123',
      unrelated: 'stays',
    });
    migrateStorage(s);
    expect(Object.fromEntries(s.data)).toEqual({
      xoraclips_theme: 'dark',
      xoraclips_language: 'id',
      xoraclips_selected_model: 'gemini-2.5-flash',
      xoraclips_cache_abc_short: '{"clips":[]}',
      xoraclips_ts_abc_short: '123',
      unrelated: 'stays',
    });
  });

  it('never carries the old plain-text Gemini key over', () => {
    const s = memoryStorage({ cheat_clip_gemini_api_key: 'AIzaSyOLD_PLAINTEXT_KEY_FROM_OLD_UI_xx' });
    migrateStorage(s);
    expect(s.data.size).toBe(0);
  });

  it('keeps a value already saved under the new name', () => {
    const s = memoryStorage({ cheat_clip_theme: 'dark', xoraclips_theme: 'light' });
    migrateStorage(s);
    expect(Object.fromEntries(s.data)).toEqual({ xoraclips_theme: 'light' });
  });

  it('is harmless when run again', () => {
    const s = memoryStorage({ cheat_clip_theme: 'dark' });
    migrateStorage(s);
    migrateStorage(s);
    expect(Object.fromEntries(s.data)).toEqual({ xoraclips_theme: 'dark' });
  });

  it('still removes the old entry when the storage is full', () => {
    const s = memoryStorage({ cheat_clip_cache_big: 'x' });
    s.setItem = () => {
      throw new DOMException('full', 'QuotaExceededError');
    };
    migrateStorage(s);
    expect(s.data.has('cheat_clip_cache_big')).toBe(false);
  });
});
