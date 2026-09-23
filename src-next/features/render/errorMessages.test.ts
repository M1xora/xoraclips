import { describe, expect, it } from 'vitest';
import { friendlyError, type FriendlyErrorStrings } from './errorMessages';

const S: FriendlyErrorStrings = {
  unknown: 'UNKNOWN',
  botVerification: 'COOKIES',
  timeout: 'TIMEOUT',
  encoder: 'ENCODER',
  diskFull: 'DISK',
  transcription: 'WHISPER',
  ffmpeg: 'FFMPEG',
  audioOnly: 'AUDIO_ONLY',
};

describe('friendlyError', () => {
  it.each([
    // The backend's own message for an audio-only download (#10), even
    // with ffmpeg's text after it: retrying later is what helps.
    [
      'YouTube only sent audio for this clip (no video track). Please try rendering again in a little while.',
      'AUDIO_ONLY',
      'retry',
    ],
    ["Sign in to confirm you're not a bot", 'COOKIES', 'cookies'],
    ['Bot verification required', 'COOKIES', 'cookies'],
    ['Download timed out after 300s', 'TIMEOUT', 'retry'],
    ['Connection timeout', 'TIMEOUT', 'retry'],
    ['ffmpeg failed: h264_nvenc not available', 'ENCODER', 'encoder'],
    ['ffmpeg error with amf encoder', 'ENCODER', 'encoder'],
    ['Hardware encoder unavailable', 'ENCODER', 'encoder'],
    ['OSError: No space left on device', 'DISK', 'clearTemp'],
    ['disk full while writing output', 'DISK', 'clearTemp'],
    ['whisper model failed to load', 'WHISPER', 'captions'],
    ['Could not transcribe audio', 'WHISPER', 'captions'],
    ['ffmpeg filter_complex parse error', 'FFMPEG', null],
  ] as const)('maps %s', (raw, message, action) => {
    const result = friendlyError(raw, S);
    expect(result.message).toBe(message);
    expect(result.action).toBe(action);
  });

  it('matches regardless of case', () => {
    expect(friendlyError('NO SPACE LEFT ON DEVICE', S).action).toBe('clearTemp');
  });

  it('checks cookies before the generic ffmpeg rule', () => {
    // Order matters: the actionable rule has to win.
    const result = friendlyError('ffmpeg: sign in to confirm', S);
    expect(result.action).toBe('cookies');
  });

  it('handles an empty message', () => {
    expect(friendlyError('', S)).toEqual({ message: 'UNKNOWN', action: null, raw: '' });
  });

  it('handles whitespace only', () => {
    expect(friendlyError('   ', S).message).toBe('UNKNOWN');
  });

  it('passes an unrecognised message through', () => {
    expect(friendlyError('Something odd happened', S).message).toBe('Something odd happened');
  });

  it('truncates a very long unrecognised message', () => {
    const long = 'x'.repeat(300);
    const result = friendlyError(long, S);
    expect(result.message).toHaveLength(143); // 140 + the ellipsis
    expect(result.message.endsWith('...')).toBe(true);
  });

  it('always keeps the raw text for the details panel', () => {
    const raw = 'ffmpeg exited with code 1';
    expect(friendlyError(raw, S).raw).toBe(raw);
  });
});
