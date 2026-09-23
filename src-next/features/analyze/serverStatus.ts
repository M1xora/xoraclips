/**
 * What the form needs to know about the server. The Gemini key always
 * comes from the user (issue #12), so the only server-side switch is
 * MOCK_MODE: sample data, no key needed.
 */

export type ServerAiStatus = 'checking' | 'normal' | 'mock' | 'unknown';

export interface HealthInfo {
  mock_mode?: boolean;
}

/**
 * `unknown` (the backend could not be reached) does not block the form:
 * the analysis request will report the real problem.
 */
export function aiStatusFromHealth(health: HealthInfo | null): ServerAiStatus {
  if (!health) return 'unknown';
  return health.mock_mode ? 'mock' : 'normal';
}
