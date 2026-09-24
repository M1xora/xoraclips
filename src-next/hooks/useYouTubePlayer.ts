import { useCallback, useEffect, useRef, useState } from 'react';
import { loadYouTubeApi, PLAYER_STATE, type YTPlayer } from '../lib/youtubeApi';
import { pauseOthers, registerPlayer } from '../lib/playbackGuard';

export interface ClipBounds {
  start: number;
  end: number;
}

interface Options {
  videoId: string;
  /** Limits playback to a clip, looping or pausing at its end. */
  bounds?: ClipBounds | null;
  loop?: boolean;
  muted?: boolean;
  controls?: boolean;
  /**
   * Whether a player that has not played yet is cued at a new clip. Off for
   * a player only ever started through play() (the Studio preview): the
   * spot is remembered and play() lands on it, so no late cue can stop
   * playback (#40).
   */
  cueWhenIdle?: boolean;
  /** How often to report playback position, in ms. */
  pollMs?: number;
}

/** True once the video has played (seekTo keeps it playing or paused). */
function hasStarted(state: number): boolean {
  return state === PLAYER_STATE.PLAYING || state === PLAYER_STATE.PAUSED || state === PLAYER_STATE.BUFFERING;
}

/**
 * How to put a player at `target` without starting it (#40).
 *
 * YouTube's seekTo() STARTS a video that has not played yet (unstarted or
 * cued). The browser held that start back until the first click anywhere on
 * the page, and then the source video began playing, with sound, next to the
 * preview. A video that has not played yet is cued at the spot instead.
 *
 * cueVideoById() lands late, so a cue still on its way when play is pressed
 * resets the player to "cued" and playback stops. So no cue is sent when the
 * player already sits there: a fresh player (it is created at the clip's
 * start) or the spot it was last cued at.
 */
export function planMove(
  state: number,
  current: number,
  target: number,
  lastCued: number | null,
): 'seek' | 'cue' | 'none' {
  if (hasStarted(state)) return 'seek';
  if (lastCued !== null) return Math.abs(lastCued - target) < 0.05 ? 'none' : 'cue';
  return Math.abs(current - target) < 1 ? 'none' : 'cue';
}

interface PlayerState {
  ready: boolean;
  playing: boolean;
  currentTime: number;
  error: string | null;
}

/**
 * Owns one YouTube player.
 *
 * Two things the previous code got wrong are handled here:
 *
 *  - Bounds and loop are read from a ref inside the polling interval, so
 *    changing them takes effect immediately. The old code captured them in
 *    a closure when playback started, so toggling loop mid-clip did nothing
 *    until the next play/pause (ClipStudioSection.tsx:415, 431).
 *
 *  - The player mounts into a div this hook creates itself, never one React
 *    renders. The old code assigned `container.innerHTML` over React-owned
 *    nodes (ClipStudioSection.tsx:339), which caused hard-to-trace flicker.
 */
export function useYouTubePlayer({
  videoId,
  bounds = null,
  loop = false,
  muted = false,
  controls = true,
  cueWhenIdle = true,
  pollMs = 200,
}: Options) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const playerRef = useRef<YTPlayer | null>(null);
  const timerRef = useRef<number | null>(null);
  const seekingRef = useRef(false);
  // Where a not-yet-started player was last cued; see planMove (#40).
  const cuedRef = useRef<number | null>(null);

  // Live values for the interval, so it never needs rebuilding.
  const boundsRef = useRef<ClipBounds | null>(bounds);
  const loopRef = useRef(loop);
  useEffect(() => {
    boundsRef.current = bounds;
  }, [bounds]);
  useEffect(() => {
    loopRef.current = loop;
  }, [loop]);

  const [state, setState] = useState<PlayerState>({
    ready: false,
    playing: false,
    currentTime: bounds?.start ?? 0,
    error: null,
  });

  const stopPolling = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    stopPolling();
    timerRef.current = window.setInterval(() => {
      const player = playerRef.current;
      if (!player || seekingRef.current) return;

      let now: number;
      try {
        now = player.getCurrentTime();
      } catch {
        return; // Player torn down between ticks.
      }

      setState((s) => (s.currentTime === now ? s : { ...s, currentTime: now }));

      const b = boundsRef.current;
      if (b && now >= b.end) {
        try {
          if (loopRef.current) {
            player.seekTo(b.start, true);
          } else {
            player.pauseVideo();
          }
        } catch {
          // Ignore: the player may be mid-teardown.
        }
      }
    }, pollMs);
  }, [pollMs, stopPolling]);

  // Create the player. Re-runs only when the video changes, so switching
  // clips seeks rather than rebuilding the iframe.
  useEffect(() => {
    if (!videoId || !hostRef.current) return;

    let cancelled = false;
    const host = hostRef.current;

    // A div this hook owns outright; React never renders into it.
    const mount = document.createElement('div');
    host.appendChild(mount);

    let unregister: (() => void) | null = null;
    loadYouTubeApi()
      .then((YT) => {
        if (cancelled) return;

        playerRef.current = new YT.Player(mount, {
          videoId,
          playerVars: {
            autoplay: 0,
            controls: controls ? 1 : 0,
            modestbranding: 1,
            rel: 0,
            playsinline: 1,
            enablejsapi: 1,
            iv_load_policy: 3,
            origin: window.location.origin,
            ...(bounds ? { start: Math.floor(bounds.start) } : {}),
          },
          events: {
            onReady: ({ target }) => {
              if (cancelled) return;
              unregister = registerPlayer(target);
              if (muted) target.mute();
              // Created at the clip's start (playerVars.start): no seek here,
              // which would start the video (#40). play() lands on the exact
              // start.
              setState((s) => ({ ...s, ready: true, error: null }));
            },
            onStateChange: ({ data, target }) => {
              if (cancelled) return;
              const playing = data === PLAYER_STATE.PLAYING;
              setState((s) => ({ ...s, playing }));

              if (playing) {
                // One sound at a time, so two players never talk over each other (#40).
                pauseOthers(target);
                startPolling();
              } else stopPolling();

              const b = boundsRef.current;
              if (data === PLAYER_STATE.ENDED && loopRef.current && b) {
                target.seekTo(b.start, true);
                target.playVideo();
              }
            },
            // Logged only. Destroying the player here wipes the container
            // and leaves a blank frame, which the old code hit and fixed
            // the same way (ClipTrimmerModal.tsx:215).
            onError: ({ data }) => console.warn('YouTube player error', data),
          },
        });
      })
      .catch((err: Error) => {
        if (!cancelled) setState((s) => ({ ...s, error: err.message }));
      });

    return () => {
      cancelled = true;
      unregister?.();
      stopPolling();
      try {
        playerRef.current?.destroy();
      } catch {
        // Already gone.
      }
      playerRef.current = null;
      mount.remove();
      setState({ ready: false, playing: false, currentTime: 0, error: null });
    };
    // `bounds`, `muted` and `controls` are read at creation only; changing a
    // clip seeks through the effect below instead of rebuilding the player.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId, startPolling, stopPolling]);

  /** Puts the player at `seconds` without starting it. */
  const moveTo = useCallback(
    (player: YTPlayer, seconds: number) => {
      let current = seconds;
      try {
        current = player.getCurrentTime();
      } catch {
        // Not ready: treat as already there.
      }
      const plan = planMove(player.getPlayerState(), current, seconds, cuedRef.current);
      if (plan === 'seek') {
        cuedRef.current = null;
        player.seekTo(seconds, true);
      } else if (plan === 'cue') {
        cuedRef.current = seconds;
        if (cueWhenIdle) player.cueVideoById({ videoId, startSeconds: seconds });
      }
    },
    [videoId, cueWhenIdle],
  );

  // Moving to another clip moves the existing player (cued, not started). The readout follows
  // only once the seek went through, as before; it is set in a microtask so
  // the effect body itself sets no state (#2).
  const boundsStart = bounds?.start;
  const boundsEnd = bounds?.end;
  useEffect(() => {
    if (!state.ready || boundsStart === undefined || !playerRef.current) return;
    try {
      moveTo(playerRef.current, boundsStart);
    } catch {
      return;
    }
    let live = true;
    queueMicrotask(() => {
      if (live) setState((s) => ({ ...s, currentTime: boundsStart }));
    });
    return () => {
      live = false;
    };
  }, [boundsStart, boundsEnd, state.ready, moveTo]);

  const seek = useCallback((seconds: number, play = false) => {
    const player = playerRef.current;
    if (!player) return;
    seekingRef.current = true;
    try {
      if (play) {
        cuedRef.current = null;
        player.seekTo(seconds, true);
        player.playVideo();
      } else {
        moveTo(player, seconds);
      }
      setState((s) => ({ ...s, currentTime: seconds }));
    } catch {
      // Ignore.
    } finally {
      // Let the player settle before polling overwrites the position.
      window.setTimeout(() => {
        seekingRef.current = false;
      }, 120);
    }
  }, [moveTo]);

  const play = useCallback(() => {
    const player = playerRef.current;
    if (!player) return;
    try {
      // The first play lands on the exact spot: the player was created at
      // the whole second, or cued at the last clip picked (#40).
      if (!hasStarted(player.getPlayerState())) {
        const at = cuedRef.current ?? boundsRef.current?.start;
        cuedRef.current = null;
        if (at !== undefined) player.seekTo(at, true);
      }
      player.playVideo();
    } catch {
      // Ignore.
    }
  }, []);

  const pause = useCallback(() => {
    try {
      playerRef.current?.pauseVideo();
    } catch {
      // Ignore.
    }
  }, []);

  const toggle = useCallback(() => {
    if (state.playing) pause();
    else play();
  }, [state.playing, play, pause]);

  /** Sound on at `volume` (0-100), or muted. The player is not rebuilt (#40). */
  const setSound = useCallback((on: boolean, volume: number) => {
    const player = playerRef.current;
    if (!player) return;
    try {
      if (on) {
        player.unMute();
        player.setVolume(volume);
        // Now audible: another player with sound should stop.
        if (player.getPlayerState() === PLAYER_STATE.PLAYING) pauseOthers(player);
      } else {
        player.mute();
      }
    } catch {
      // Ignore.
    }
  }, []);

  return { hostRef, ...state, seek, play, pause, toggle, setSound };
}
