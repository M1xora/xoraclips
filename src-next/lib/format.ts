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
