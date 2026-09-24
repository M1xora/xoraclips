/**
 * Volume of the source video in the Studio preview (#40).
 *
 * The render takes "original audio volume" up to 200%; the YouTube player
 * stops at 100, so a boost is only heard in the render.
 */
export const PREVIEW_MAX_VOLUME = 100;

export function previewVolume(originalAudioVolume: number): number {
  if (!Number.isFinite(originalAudioVolume)) return PREVIEW_MAX_VOLUME;
  return Math.round(Math.min(PREVIEW_MAX_VOLUME, Math.max(0, originalAudioVolume)));
}

/** True when the preview is quieter than the render will be. */
export function boostedBeyondPreview(originalAudioVolume: number): boolean {
  return originalAudioVolume > PREVIEW_MAX_VOLUME;
}
