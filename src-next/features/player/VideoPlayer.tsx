import { useEffect, useMemo } from 'react';
import { PauseIcon, PlayIcon, WarningCircleIcon } from '@phosphor-icons/react';
import { useYouTubePlayer, type ClipBounds } from '../../hooks/useYouTubePlayer';
import { HeatmapTimeline } from './HeatmapTimeline';
import type { AnalyzeResponse, ViralClip } from '../../lib/types';

interface VideoPlayerProps {
  result: AnalyzeResponse;
  activeClip: ViralClip | null;
  /** Set when the user picked a clip, so the source jumps to its start. */
  seekToClip: boolean;
  heatmapLabel: string;
  heatmapEmptyLabel: string;
  onPlayed: () => void;
}

export function VideoPlayer({
  result,
  activeClip,
  seekToClip,
  heatmapLabel,
  heatmapEmptyLabel,
  onPlayed,
}: VideoPlayerProps) {
  // A new object each render would re-seek constantly, so bounds are memoised
  // on the values that actually matter.
  const clipStart = activeClip?.start_time;
  const clipEnd = activeClip?.end_time;
  const bounds: ClipBounds | null = useMemo(
    () => (clipStart !== undefined && clipEnd !== undefined ? { start: clipStart, end: clipEnd } : null),
    [clipStart, clipEnd],
  );

  const { hostRef, ready, playing, currentTime, error, seek, toggle } = useYouTubePlayer({
    videoId: result.video_id,
    bounds,
    loop: false,
    controls: true,
  });

  // Jump to the clip without playing. Only the portrait preview plays, so
  // the two players never sound at the same time.
  useEffect(() => {
    if (!seekToClip || !ready || !bounds) return;
    seek(bounds.start, false);
    onPlayed();
  }, [seekToClip, ready, bounds, seek, onPlayed]);

  return (
    <div>
      <div className="relative aspect-video overflow-hidden rounded-[--radius-control] bg-surface-2">
        {/* The hook mounts the iframe into a child it owns. */}
        <div ref={hostRef} className="size-full [&>div]:size-full [&_iframe]:size-full" />

        {!ready && !error && (
          <div className="skeleton absolute inset-0" aria-hidden="true" />
        )}

        {error && (
          <div className="absolute inset-0 grid place-items-center p-4 text-center">
            <div>
              <WarningCircleIcon
                size={20}
                weight="fill"
                className="mx-auto text-critical-text"
              />
              <p className="mt-2 text-xs text-ink-dim">{error}</p>
            </div>
          </div>
        )}
      </div>

      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          onClick={toggle}
          disabled={!ready}
          aria-label={playing ? 'Pause' : 'Play'}
          className="pressable grid size-8 shrink-0 place-items-center rounded-[--radius-control]
            border border-hairline bg-surface-2 hover:bg-surface-3 disabled:opacity-40"
        >
          {playing ? <PauseIcon size={14} weight="fill" /> : <PlayIcon size={14} weight="fill" />}
        </button>

        <div className="min-w-0 flex-1">
          <HeatmapTimeline
            duration={result.duration}
            heatmap={result.heatmap}
            currentTime={currentTime}
            activeClip={activeClip}
            onSeek={(s) => seek(s, true)}
            label={heatmapLabel}
            emptyLabel={heatmapEmptyLabel}
          />
        </div>
      </div>
    </div>
  );
}
