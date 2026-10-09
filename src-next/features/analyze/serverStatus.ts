/**
 * What the form needs to know about the server. The Gemini key always
 * comes from the user (issue #12), so the only server-side switch is
 * MOCK_MODE: sample data, no key needed.
 */

export type ServerAiStatus = 'checking' | 'normal' | 'mock' | 'unknown';

export interface HealthInfo {
  mock_mode?: boolean;
  /** Whether automatic subtitles are installed; optional since #112. */
  whisper_available?: boolean;
}

/**
 * Whether the Studio should warn that automatic subtitles are missing.
 *
 * Only `false` warns. A backend that could not be reached, or an older one
 * that does not send the field, must stay quiet: a warning shown on a guess
 * is worse than none, because the user cannot tell which case they are in.
 */
export function whisperMissing(health: HealthInfo | null): boolean {
  return health?.whisper_available === false;
}

/**
 * `unknown` (the backend could not be reached) does not block the form:
 * the analysis request will report the real problem.
 */
export function aiStatusFromHealth(health: HealthInfo | null): ServerAiStatus {
  if (!health) return 'unknown';
  return health.mock_mode ? 'mock' : 'normal';
}
