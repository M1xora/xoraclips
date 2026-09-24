/**
 * Volume of the source video in the Studio preview (#40).
 *
 * The render takes "original audio volume" (and the hook SFX) up to 200%;
 * the YouTube player and the browser stop at 100, so a boost is only heard
 * in the render.
 */
export const PREVIEW_MAX_VOLUME = 100;

/** A percentage, with a bad value read as the default 100. */
function percent(value: number): number {
  return Number.isFinite(value) ? Math.max(0, value) : PREVIEW_MAX_VOLUME;
}

export function previewVolume(originalAudioVolume: number): number {
  return Math.round(Math.min(PREVIEW_MAX_VOLUME, percent(originalAudioVolume)));
}

/** True when the preview is quieter than the render will be. */
export function boostedBeyondPreview(...volumes: number[]): boolean {
  return volumes.some((v) => percent(v) > PREVIEW_MAX_VOLUME);
}
