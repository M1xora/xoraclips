/**
 * Turns a raw render failure into something the user can act on.
 *
 * Ported from ClipStudioSection.tsx:33-57. This is the only bridge between
 * an ffmpeg or yt-dlp stack trace and the button that fixes it, so dropping
 * it during the rewrite would have left users staring at raw output.
 *
 * Unlike the original, the recovery action is returned separately from the
 * text, so the UI can show a real button instead of describing one.
 */

export type RecoveryAction = 'cookies' | 'encoder' | 'clearTemp' | 'captions' | 'retry' | null;

export interface FriendlyError {
  message: string;
  action: RecoveryAction;
  /** The untouched backend message, kept for the details panel. */
  raw: string;
}

interface Rule {
  match: (lower: string) => boolean;
  action: RecoveryAction;
  key: keyof FriendlyErrorStrings;
}

export interface FriendlyErrorStrings {
  unknown: string;
  botVerification: string;
  timeout: string;
  encoder: string;
  diskFull: string;
  transcription: string;
  ffmpeg: string;
  audioOnly: string;
}

const RULES: Rule[] = [
  {
    // backend/video_engine.py AUDIO_ONLY_MESSAGE (#10). Before the ffmpeg
    // rule: a retry later usually works, the ffmpeg text would not help.
    match: (s) => s.includes('only sent audio'),
    action: 'retry',
    key: 'audioOnly',
  },
  {
    match: (s) =>
      s.includes('bot verification') ||
      s.includes('sign in') ||
      s.includes("confirm you're not a bot"),
    action: 'cookies',
    key: 'botVerification',
  },
  {
    match: (s) => s.includes('timed out') || s.includes('timeout'),
    action: 'retry',
    key: 'timeout',
  },
  {
    match: (s) =>
      s.includes('hardware encoder') ||
      (s.includes('ffmpeg') &&
        (s.includes('nvenc') || s.includes('amf') || s.includes('qsv'))),
    action: 'encoder',
    key: 'encoder',
  },
  {
    match: (s) =>
      s.includes('no space left') || s.includes('disk full') || s.includes('out of disk'),
    action: 'clearTemp',
    key: 'diskFull',
  },
  {
    match: (s) => s.includes('whisper') || s.includes('transcribe'),
    action: 'captions',
    key: 'transcription',
  },
  {
    match: (s) => s.includes('ffmpeg') || s.includes('filter_complex'),
    action: null,
    key: 'ffmpeg',
  },
];

export function friendlyError(raw: string, strings: FriendlyErrorStrings): FriendlyError {
  if (!raw?.trim()) return { message: strings.unknown, action: null, raw: '' };

  const lower = raw.toLowerCase();
  const rule = RULES.find((r) => r.match(lower));

  if (rule) return { message: strings[rule.key], action: rule.action, raw };

  // Nothing matched: show the backend's own words, trimmed.
  return {
    message: raw.length > 140 ? `${raw.slice(0, 140)}...` : raw,
    action: null,
    raw,
  };
}
