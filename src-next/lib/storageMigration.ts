/**
 * The app was renamed from its old name to Xoraclips (issue #14), and so
 * were its browser-storage names. This moves what users already saved
 * (theme, language, model, analysis history and cache) to the new names,
 * once, so nothing is lost. This file is the only place the old prefix is
 * still written down, because it has to recognise the old data.
 */

const OLD_PREFIX = 'cheat_clip_';
const NEW_PREFIX = 'xoraclips_';
/** The old UI's plain-text Gemini key: deleted, never carried over. */
const OLD_KEY_SLOT = `${OLD_PREFIX}gemini_api_key`;

type StorageLike = Pick<Storage, 'length' | 'key' | 'getItem' | 'setItem' | 'removeItem'>;

export function migrateStorage(storage: StorageLike): void {
  const oldNames: string[] = [];
  for (let i = 0; i < storage.length; i += 1) {
    const name = storage.key(i);
    if (name?.startsWith(OLD_PREFIX)) oldNames.push(name);
  }

  for (const oldName of oldNames) {
    const newName = NEW_PREFIX + oldName.slice(OLD_PREFIX.length);
    const value = storage.getItem(oldName);
    storage.removeItem(oldName);
    // Something already saved under the new name is newer: keep it.
    if (oldName === OLD_KEY_SLOT || value === null || storage.getItem(newName) !== null) continue;
    // Removed first, so a big cache entry does not need twice its size.
    try {
      storage.setItem(newName, value);
    } catch {
      // Still no room: put it back under the old name rather than lose it.
      try {
        storage.setItem(oldName, value);
      } catch {
        // Nothing more we can do; it was only a cache or a setting.
      }
    }
  }
}

/** Runs before the app starts, so every part reads the new names. */
export function migrateBrowserStorage(): void {
  for (const get of [() => window.localStorage, () => window.sessionStorage]) {
    try {
      migrateStorage(get());
    } catch {
      // Storage blocked (private mode): nothing saved, nothing to move.
    }
  }
}
