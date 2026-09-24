import type { Translations } from '../../i18n/id';

/**
 * Target clip lengths the backend accepts (backend/clip_lengths.py). Any other
 * value is refused with 422, so this list and the backend's must match.
 */
export const CLIP_DURATIONS = ['15s', '30s', '60s', '120s', '180s'] as const;

export type ClipDuration = (typeof CLIP_DURATIONS)[number];

const LABELS: Record<ClipDuration, string> = {
  '15s': '15s',
  '30s': '30s',
  '60s': '60s',
  '120s': '2m',
  '180s': '3m',
};

export function durationOptions(t: Translations) {
  const subs: Record<ClipDuration, string> = {
    '15s': t.form.durationHook,
    '30s': t.form.durationShorts,
    '60s': t.form.durationStory,
    '120s': t.form.durationContext,
    '180s': t.form.durationFull,
  };
  return CLIP_DURATIONS.map((value) => ({ value, label: LABELS[value], sub: subs[value] }));
}
