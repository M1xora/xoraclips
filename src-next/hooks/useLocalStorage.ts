import { useCallback, useEffect, useState } from 'react';

/**
 * State that persists to localStorage.
 *
 * Every read and write is guarded: localStorage throws in private windows,
 * when site data is blocked, and when the quota is exceeded. The old frontend
 * called setItem() directly inside onChange handlers, so a quota error there
 * would break the input.
 */
export function useLocalStorage<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? initial : (JSON.parse(raw) as T);
    } catch {
      return initial;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch {
      // Quota exceeded or storage blocked - keep working from memory.
    }
  }, [key, value]);

  const clear = useCallback(() => {
    try {
      localStorage.removeItem(key);
    } catch {
      // Nothing to do if storage is unavailable.
    }
  }, [key]);

  return [value, setValue, clear] as const;
}

/**
 * Same as useLocalStorage but stores the raw string.
 * Used for secrets and plain text, where JSON quoting only adds noise.
 */
export function useLocalStorageString(key: string, initial = '') {
  const [value, setValue] = useState<string>(() => {
    try {
      return localStorage.getItem(key) ?? initial;
    } catch {
      return initial;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(key, value);
    } catch {
      // Ignore - see above.
    }
  }, [key, value]);

  return [value, setValue] as const;
}
