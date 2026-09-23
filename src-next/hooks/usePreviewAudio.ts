import { useEffect, useRef } from 'react';

/**
 * Plays the BGM and hook SFX alongside the preview.
 *
 * The old studio saved these settings and sent them to the render, but the
 * preview stayed silent, so the only way to hear a volume choice was to
 * render the clip and watch the result.
 *
 * This mirrors what video_engine.py does when it mixes the audio:
 *   BGM  starts at `bgmStartOffset` into the track, loops to fill the clip,
 *        and fades out over the last 1.5 seconds (video_engine.py:1686-1694).
 *   SFX  plays once from the first frame (video_engine.py:1699-1707).
 *
 * It is a preview, not the mix: the browser cannot reproduce ffmpeg's amix
 * normalisation, so levels are indicative rather than exact.
 */

/** Seconds of fade at the end of the clip, matching afade d=1.5. */
export const FADE_SEC = 1.5;

/**
 * BGM gain at a point in the clip, as a 0..1 multiplier.
 *
 * video_engine.py:1692 applies `afade=t=out:st=dur-1.5:d=1.5`, so the track
 * plays flat until the last 1.5 seconds and then ramps to silence.
 */
export function bgmFade(elapsed: number, duration: number): number {
  const remaining = duration - elapsed;
  if (remaining >= FADE_SEC) return 1;
  return Math.max(0, Math.min(1, remaining / FADE_SEC));
}

/**
 * Where in the music track the renderer would be at this moment.
 *
 * ffmpeg seeks `-ss offset` then loops with `-stream_loop -1`, so the track
 * wraps around its own length (video_engine.py:1686-1689).
 */
export function bgmSeekTarget(offset: number, elapsed: number, trackLen: number): number {
  const want = offset + elapsed;
  if (!Number.isFinite(trackLen) || trackLen <= 0) return want;
  return want % trackLen;
}

export interface PreviewAudioOptions {
  /** Served URL of the uploaded track, or null when none is set. */
  bgmUrl: string | null;
  bgmEnabled: boolean;
  /** Percent, 0..100. main.py:2388 divides by 100 before the engine. */
  bgmVolume: number;
  /** Seconds into the track where playback starts. */
  bgmStartOffset: number;

  sfxUrl: string | null;
  sfxEnabled: boolean;
  /** Percent, 0..200. main.py:2392 divides by 100 before the engine. */
  sfxVolume: number;

  /** Whether the preview video is playing right now. */
  playing: boolean;
  /** Seconds elapsed within the clip. */
  elapsed: number;
  /** Total clip length in seconds. */
  duration: number;
  /** When false, nothing is audible at all. */
  enabled: boolean;
}

export function usePreviewAudio({
  bgmUrl,
  bgmEnabled,
  bgmVolume,
  bgmStartOffset,
  sfxUrl,
  sfxEnabled,
  sfxVolume,
  playing,
  elapsed,
  duration,
  enabled,
}: PreviewAudioOptions) {
  const bgmRef = useRef<HTMLAudioElement | null>(null);
  const sfxRef = useRef<HTMLAudioElement | null>(null);

  // Keep the latest elapsed time without making the play effect depend on it,
  // which would restart the track on every poll tick.
  const elapsedRef = useRef(elapsed);
  // Written after render (refs are not written during render, #2). Declared
  // before the play effects, so they read this commit's value.
  useEffect(() => {
    elapsedRef.current = elapsed;
  }, [elapsed]);

  const bgmOn = enabled && bgmEnabled && !!bgmUrl;
  const sfxOn = enabled && sfxEnabled && !!sfxUrl;

  // ------------------------------------------------------------------ BGM
  useEffect(() => {
    if (!bgmOn || !bgmUrl) return;

    const el = new Audio(bgmUrl);
    el.loop = true;
    el.preload = 'auto';
    bgmRef.current = el;

    return () => {
      el.pause();
      el.src = '';
      bgmRef.current = null;
    };
  }, [bgmOn, bgmUrl]);

  // ------------------------------------------------------------------ SFX
  useEffect(() => {
    if (!sfxOn || !sfxUrl) return;

    const el = new Audio(sfxUrl);
    el.preload = 'auto';
    sfxRef.current = el;

    return () => {
      el.pause();
      el.src = '';
      sfxRef.current = null;
    };
  }, [sfxOn, sfxUrl]);

  // Volume, with the same fade-out the renderer applies at the end.
  useEffect(() => {
    const el = bgmRef.current;
    if (!el) return;

    el.volume = clamp01(bgmVolume / 100) * bgmFade(elapsed, duration);
  }, [bgmVolume, elapsed, duration]);

  useEffect(() => {
    const el = sfxRef.current;
    if (!el) return;
    // The backend allows up to 2x; the browser caps at 1, so a boost above
    // 100% sounds the same here but is still sent to the render.
    el.volume = clamp01(sfxVolume / 100);
  }, [sfxVolume]);

  // Follow the video: play, pause, and stay roughly in sync.
  useEffect(() => {
    const el = bgmRef.current;
    if (!el) return;

    if (!playing) {
      el.pause();
      return;
    }

    const target = bgmSeekTarget(bgmStartOffset, elapsedRef.current, el.duration);

    if (Math.abs(el.currentTime - target) > 0.35) {
      try {
        el.currentTime = target;
      } catch {
        // Seeking before metadata loads throws; the next tick retries.
      }
    }

    void el.play().catch(() => {
      // Autoplay can be refused until the user interacts with the page.
    });
  }, [playing, bgmStartOffset, bgmOn]);

  // The SFX is a one-shot at the start of the clip, so it restarts whenever
  // playback returns to the beginning rather than following the playhead.
  const firedRef = useRef(false);

  useEffect(() => {
    const el = sfxRef.current;
    if (!el) return;

    if (!playing) {
      el.pause();
      return;
    }

    if (elapsed < 0.4) {
      if (!firedRef.current) {
        firedRef.current = true;
        el.currentTime = 0;
        void el.play().catch(() => {});
      }
    } else {
      firedRef.current = false;
    }
  }, [playing, elapsed]);
}

function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v));
}
