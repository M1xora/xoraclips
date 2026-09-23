/**
 * The user's Gemini key (issue #12). Users pay for their own AI usage, so
 * the key is typed in the form, kept in the browser if they choose, and sent
 * only in the X-Gemini-Api-Key header. The server never stores it.
 *
 * "Remember" on  -> localStorage (survives closing the browser)
 * "Remember" off -> sessionStorage (gone when the tab closes)
 *
 * The current value is also held in memory, so the app keeps working when
 * browser storage is blocked (private mode, blocked site data).
 */

// Not the old UI's slot ('cheat_clip_gemini_api_key'): the old UI in src/ is
// served on the same origin and sends whatever it finds there in the URL.
const KEY_STORAGE = 'xoraclips_gemini_key';
const REMEMBER_STORAGE = 'xoraclips_remember_gemini_key';
/** Plain-text keys left by older versions; removed on load. */
export const LEGACY_KEY_STORAGE = 'cheat_clip_gemini_api_key';

type StorageLike = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

export interface KeyStorages {
  local: () => StorageLike | undefined;
  session: () => StorageLike | undefined;
}

// Getters, because in some browsers merely reading window.localStorage throws.
const browserStorages: KeyStorages = {
  local: () => window.localStorage,
  session: () => window.sessionStorage,
};

let memory = '';

function attempt(fn: () => void): void {
  try {
    fn();
  } catch {
    // Storage unavailable: the in-memory copy still works for this page.
  }
}

function read(get: () => StorageLike | undefined, name: string): string | null {
  try {
    return get()?.getItem(name) ?? null;
  } catch {
    return null;
  }
}

export function loadApiKey(storages: KeyStorages = browserStorages): { key: string; remember: boolean } {
  attempt(() => storages.local()?.removeItem(LEGACY_KEY_STORAGE));
  const remember = read(storages.local, REMEMBER_STORAGE) !== 'false';
  const stored = read(storages.session, KEY_STORAGE) ?? read(storages.local, KEY_STORAGE);
  if (stored !== null) memory = stored;
  return { key: memory, remember };
}

export function saveApiKey(key: string, remember: boolean, storages: KeyStorages = browserStorages): void {
  memory = key;
  attempt(() => storages.local()?.setItem(REMEMBER_STORAGE, String(remember)));
  const value = key.trim();
  const keep = remember ? storages.local : storages.session;
  const drop = remember ? storages.session : storages.local;
  attempt(() => drop()?.removeItem(KEY_STORAGE));
  attempt(() => (value ? keep()?.setItem(KEY_STORAGE, value) : keep()?.removeItem(KEY_STORAGE)));
}

/** "Delete saved key": removes it from memory and from both storages. */
export function clearApiKey(storages: KeyStorages = browserStorages): void {
  memory = '';
  attempt(() => storages.local()?.removeItem(KEY_STORAGE));
  attempt(() => storages.session()?.removeItem(KEY_STORAGE));
}

/** The key to send with the next request, trimmed; '' when none. */
export function currentApiKey(): string {
  return memory.trim();
}

/** Where users create a free key. */
export const AI_STUDIO_KEY_URL = 'https://aistudio.google.com/apikey';
