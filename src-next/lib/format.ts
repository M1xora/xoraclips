/**
 * Formatting helpers.
 *
 * The old code had three different formatSeconds implementations that
 * disagreed on zero-padding. This is the single version.
 */

/** Seconds to H:MM:SS past an hour, otherwise MM:SS. Minutes always padded. */
export function formatTimecode(totalSeconds: number): string {
  const secs = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;

  const mm = String(m).padStart(2, '0');
  const ss = String(s).padStart(2, '0');

  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/**
 * Seconds with hundredths when there are any: "00:17.28", "01:23.5",
 * "1:01:23". The same padding as formatTimecode, for times typed or cut at a
 * transcript line (#56).
 */
export function formatPreciseTimecode(totalSeconds: number): string {
  const total = Math.max(0, Math.round(totalSeconds * 100) / 100);
  const whole = Math.floor(total);
  const hundredths = Math.round((total - whole) * 100);
  const tail = hundredths > 0 ? `.${String(hundredths).padStart(2, '0').replace(/0$/, '')}` : '';
  return formatTimecode(whole) + tail;
}

/**
 * "83", "83.5", "1:23", "01:23.5" or "1:01:23" to seconds; null for anything
 * else (minutes and seconds after a colon must be under 60). A comma works as
 * the decimal mark too.
 */
export function parseTimecode(text: string): number | null {
  const raw = text.trim().replace(',', '.');
  if (!/^\d+(:\d{1,2}){0,2}(\.\d+)?$/.test(raw)) return null;
  const parts = raw.split(':');
  const seconds = Number(parts.pop());
  if (parts.length > 0 && seconds >= 60) return null;
  const minutes = parts.length > 0 ? Number(parts.pop()) : 0;
  if (parts.length > 0 && minutes >= 60) return null;
  const hours = parts.length > 0 ? Number(parts.pop()) : 0;
  return hours * 3600 + minutes * 60 + seconds;
}

/** Byte count to a human readable size. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unit]}`;
}

/** Strips characters Windows rejects in filenames. */
export function sanitizeFilename(name: string): string {
  return name.replace(/[\\/*?:"<>|]/g, '').trim();
}
