/**
 * Loads the YouTube IFrame API once for the whole page.
 *
 * `window.onYouTubeIframeAPIReady` is a single global callback. The previous
 * code assigned it from whichever component happened to mount (App.tsx:408),
 * so a second component overwrote the first one's callback and that player
 * never initialised. This module owns the global and hands every caller the
 * same promise.
 */

export interface YTPlayer {
  playVideo(): void;
  pauseVideo(): void;
  seekTo(seconds: number, allowSeekAhead: boolean): void;
  getCurrentTime(): number;
  getPlayerState(): number;
  mute(): void;
  unMute(): void;
  /** 0-100. */
  setVolume(volume: number): void;
  destroy(): void;
  loadVideoById(id: string): void;
  unloadModule?(name: string): void;
}

export interface YTPlayerOptions {
  videoId: string;
  playerVars?: Record<string, string | number>;
  events?: {
    onReady?: (e: { target: YTPlayer }) => void;
    onStateChange?: (e: { data: number; target: YTPlayer }) => void;
    onError?: (e: { data: number }) => void;
  };
}

interface YTNamespace {
  Player: new (el: HTMLElement | string, opts: YTPlayerOptions) => YTPlayer;
  PlayerState: { ENDED: 0; PLAYING: 1; PAUSED: 2; BUFFERING: 3; CUED: 5 };
}

declare global {
  interface Window {
    YT?: YTNamespace;
    onYouTubeIframeAPIReady?: () => void;
  }
}

const SCRIPT_ID = 'youtube-iframe-api';
let loader: Promise<YTNamespace> | null = null;

/** Resolves once `window.YT.Player` is usable. Safe to call many times. */
export function loadYouTubeApi(): Promise<YTNamespace> {
  if (loader) return loader;

  loader = new Promise<YTNamespace>((resolve, reject) => {
    if (window.YT?.Player) {
      resolve(window.YT);
      return;
    }

    // Whoever gets here first owns the global callback.
    window.onYouTubeIframeAPIReady = () => {
      if (window.YT?.Player) resolve(window.YT);
      else reject(new Error('YouTube API loaded without a Player constructor'));
    };

    if (!document.getElementById(SCRIPT_ID)) {
      const script = document.createElement('script');
      script.id = SCRIPT_ID;
      script.src = 'https://www.youtube.com/iframe_api';
      script.async = true;
      script.onerror = () => reject(new Error('Could not load the YouTube IFrame API'));
      document.head.appendChild(script);
    }

    // The API occasionally arrives without firing the callback.
    setTimeout(() => {
      if (window.YT?.Player) resolve(window.YT);
      else reject(new Error('YouTube IFrame API timed out'));
    }, 15000);
  });

  // A failed load should not poison later attempts.
  loader.catch(() => {
    loader = null;
  });

  return loader;
}

export const PLAYER_STATE = {
  ENDED: 0,
  PLAYING: 1,
  PAUSED: 2,
  BUFFERING: 3,
  CUED: 5,
} as const;
