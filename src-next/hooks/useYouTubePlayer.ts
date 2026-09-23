import { useCallback, useEffect, useRef, useState } from 'react';
import { loadYouTubeApi, PLAYER_STATE, type YTPlayer } from '../lib/youtubeApi';

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
  /** How often to report playback position, in ms. */
  pollMs?: number;
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
  pollMs = 200,
}: Options) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const playerRef = useRef<YTPlayer | null>(null);
  const timerRef = useRef<number | null>(null);
  const seekingRef = useRef(false);

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
              if (muted) target.mute();
              if (bounds) target.seekTo(bounds.start, true);
              setState((s) => ({ ...s, ready: true, error: null }));
            },
            onStateChange: ({ data, target }) => {
              if (cancelled) return;
              const playing = data === PLAYER_STATE.PLAYING;
              setState((s) => ({ ...s, playing }));

              if (playing) startPolling();
              else stopPolling();

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

  // Moving to another clip seeks the existing player. The readout follows
  // only once the seek went through, as before; it is set in a microtask so
  // the effect body itself sets no state (#2).
  const boundsStart = bounds?.start;
  const boundsEnd = bounds?.end;
  useEffect(() => {
    if (!state.ready || boundsStart === undefined || !playerRef.current) return;
    try {
      playerRef.current.seekTo(boundsStart, true);
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
  }, [boundsStart, boundsEnd, state.ready]);

  const seek = useCallback((seconds: number, play = false) => {
    const player = playerRef.current;
    if (!player) return;
    seekingRef.current = true;
    try {
      player.seekTo(seconds, true);
      setState((s) => ({ ...s, currentTime: seconds }));
      if (play) player.playVideo();
    } catch {
      // Ignore.
    } finally {
      // Let the player settle before polling overwrites the position.
      window.setTimeout(() => {
        seekingRef.current = false;
      }, 120);
    }
  }, []);

  const play = useCallback(() => {
    try {
      playerRef.current?.playVideo();
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

  return { hostRef, ...state, seek, play, pause, toggle };
}
