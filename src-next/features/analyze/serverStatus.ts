/**
 * The Gemini key lives only on the server (backend/.env, issue #8). The
 * browser never asks for it, stores it, or sends it. This module tells the
 * form whether the server is ready, and removes keys that older versions of
 * the app left in the browser.
 */

/** Where older versions stored the user's key in plain text. */
export const LEGACY_API_KEY_STORAGE = 'cheat_clip_gemini_api_key';

/**
 * Deletes a key left behind by an older version. Returns true when one was
 * removed. Never throws: storage can be unavailable (private mode, blocked
 * site data), and in some browsers merely reading `window.localStorage`
 * throws, which is why it is passed as a getter.
 */
export function purgeLegacyApiKey(
  getStorage: () => Pick<Storage, 'getItem' | 'removeItem'> | undefined,
): boolean {
  try {
    const storage = getStorage();
    if (!storage || storage.getItem(LEGACY_API_KEY_STORAGE) === null) return false;
    storage.removeItem(LEGACY_API_KEY_STORAGE);
    return true;
  } catch {
    return false;
  }
}

export type ServerAiStatus = 'checking' | 'ready' | 'mock' | 'notConfigured' | 'unknown';

export interface HealthInfo {
  gemini_env_configured?: boolean;
  mock_mode?: boolean;
}

/**
 * What the form should do, from /api/health. `unknown` (the backend could
 * not be reached) does not block the form: the analysis request will report
 * the real problem.
 */
export function aiStatusFromHealth(health: HealthInfo | null): ServerAiStatus {
  if (!health) return 'unknown';
  if (health.mock_mode) return 'mock';
  return health.gemini_env_configured ? 'ready' : 'notConfigured';
}
