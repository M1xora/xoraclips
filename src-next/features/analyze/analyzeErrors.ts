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

export interface RetryInfo {
  /** When the server will try YouTube again (ms since epoch), if it said. */
  retryAt?: number | null;
  now?: number;
  /** BCP 47 locale for the clock time, e.g. 'id-ID'. */
  locale?: string;
}

export function analyzeErrorView(
  code: string | null,
  fallbackMessage: string,
  t: Translations,
  retry: RetryInfo = {},
): AnalyzeErrorView {
  switch (code) {
    case 'youtube_blocked':
      return { message: youtubeBlockedMessage(t, retry), keyProblem: false };
    case 'captions_disabled':
      return { message: t.errors.captionsDisabled, keyProblem: false };
    case 'video_unavailable':
      return { message: t.errors.videoUnavailable, keyProblem: false };
    case 'age_restricted':
      return { message: t.errors.ageRestricted, keyProblem: false };
    case 'video_live':
      return { message: t.errors.videoLive, keyProblem: false };
    case 'captions_unavailable':
      return { message: t.errors.captionsUnavailable, keyProblem: false };
    case 'key_missing':
      return { message: t.errors.keyMissing, keyProblem: true };
    case 'key_invalid':
      return { message: t.errors.keyInvalid, keyProblem: true };
    case 'key_quota':
      return { message: t.errors.keyQuota, keyProblem: true };
    case 'region_unsupported':
      return { message: t.errors.regionUnsupported, keyProblem: false };
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

/**
 * "Try again after 14:35 (about 10 minutes)". The time is when the server
 * stops staying away from YouTube (issue #9), not a promise that YouTube
 * has lifted the block by then.
 */
function youtubeBlockedMessage(t: Translations, { retryAt, now = Date.now(), locale }: RetryInfo): string {
  if (!retryAt || retryAt <= now) return t.errors.youtubeBlockedLater;
  const minutes = Math.max(1, Math.ceil((retryAt - now) / 60_000));
  const time = new Date(retryAt).toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' });
  return t.errors.youtubeBlocked(time, minutes);
}

/** Moves focus to the key field so the user can paste a new key. */
export function focusApiKeyField(inputName: string): void {
  const input = document.querySelector<HTMLInputElement>(`input[name="${inputName}"]`);
  if (!input) return;
  input.scrollIntoView({ behavior: 'smooth', block: 'center' });
  input.focus();
  input.select();
}
