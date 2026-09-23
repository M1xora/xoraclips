import type { DownloadNote } from '../../lib/types';
import type { Translations } from '../../i18n/id';

/**
 * The line under a clip while it downloads, so a retry or a switch to
 * another download method does not look like the app froze (#10).
 */
export function downloadNoteText(note: DownloadNote | undefined, t: Translations): string | null {
  if (!note) return null;
  if (note.code === 'audio_only_retry') return t.render.downloadRetry(note.method, note.methods);
  if (note.code === 'next_method') return t.render.downloadNextMethod(note.method, note.methods);
  return null;
}
