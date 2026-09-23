import type { Translations } from '../../i18n/id';

/**
 * How to show an analysis failure, from the backend's error code
 * (backend/ai_errors.py). Key problems get a "change key" action, because
 * the key is the user's own and only they can fix it (issue #12).
 */
export interface AnalyzeErrorView {
  message: string;
  /** Show "Change key" and the AI Studio link. */
  keyProblem: boolean;
}

export function analyzeErrorView(
  code: string | null,
  fallbackMessage: string,
  t: Translations,
): AnalyzeErrorView {
  switch (code) {
    case 'key_missing':
      return { message: t.errors.keyMissing, keyProblem: true };
    case 'key_invalid':
      return { message: t.errors.keyInvalid, keyProblem: true };
    case 'key_quota':
      return { message: t.errors.keyQuota, keyProblem: true };
    case 'model_unavailable':
      return { message: t.errors.modelUnavailable, keyProblem: false };
    case 'ai_busy':
      return { message: t.errors.aiBusy, keyProblem: false };
    case 'ai_failed':
      return { message: t.errors.aiFailed, keyProblem: false };
    default:
      // Not an AI problem (YouTube, network...): show what the server said.
      return { message: fallbackMessage, keyProblem: false };
  }
}

/** Moves focus to the key field so the user can paste a new key. */
export function focusApiKeyField(inputName: string): void {
  const input = document.querySelector<HTMLInputElement>(`input[name="${inputName}"]`);
  if (!input) return;
  input.scrollIntoView({ behavior: 'smooth', block: 'center' });
  input.focus();
  input.select();
}
