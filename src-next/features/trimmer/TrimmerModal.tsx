import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowCounterClockwiseIcon } from '@phosphor-icons/react';
import { Button } from '../../components/ui/Button';
import { Modal } from '../../components/ui/Modal';
import { useYouTubePlayer } from '../../hooks/useYouTubePlayer';
import { formatTimecode } from '../../lib/format';
import { useLanguage } from '../../i18n';
import {
  buildTimeline,
  clampEnd,
  clampPlayhead,
  clampStart,
  percentToTime,
  slideWindow,
  timeToPercent,
} from './trimMath';
import type { ViralClip } from '../../lib/types';

type DragKind = 'start' | 'end' | 'playhead' | 'window';

interface DragInfo {
  kind: DragKind;
  startClientX: number;
  initialStart: number;
  duration: number;
}

interface TrimmerModalProps {
  open: boolean;
  clip: ViralClip;
  videoId: string;
  videoDuration: number;
  onApply: (adjusted: ViralClip) => void;
  onClose: () => void;
}

/**
 * Adjusts a clip's in and out points.
 *
 * Two departures from the original, both deliberate:
 *
 *  - The modal is mounted only when it is open, so the null-clip crash at
 *    ClipTrimmerModal.tsx:69 cannot happen.
 *  - Applying a trim is its own button. The original saved the new bounds
 *    only as a side effect of pressing Download, which meant no download, no
 *    saved trim.
 */
export function TrimmerModal({
  open,
  clip,
  videoId,
  videoDuration,
  onApply,
  onClose,
}: TrimmerModalProps) {
  const { t } = useLanguage();
  const tl = buildTimeline(clip.start_time, clip.end_time, videoDuration);

  const [start, setStart] = useState(clip.start_time);
  const [end, setEnd] = useState(clip.end_time);
  const [head, setHead] = useState(clip.start_time);

  const trackRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<DragInfo | null>(null);
  const seekTimer = useRef<number | null>(null);

  const { hostRef, ready, seek } = useYouTubePlayer({
    videoId,
    bounds: null,
    controls: true,
  });

  useEffect(() => {
    if (ready) seek(clip.start_time, false);
  }, [ready, clip.start_time, seek]);

  /**
   * Leading-edge throttle: the first move schedules a seek, the rest inside
   * the window are dropped. A precise seek follows on pointer up, so the
   * final position is exact without flooding the iframe.
   */
  const throttledSeek = useCallback(
    (time: number) => {
      if (seekTimer.current !== null) return;
      seekTimer.current = window.setTimeout(() => {
        seekTimer.current = null;
        seek(time, false);
      }, 120);
    },
    [seek],
  );

  useEffect(
    () => () => {
      if (seekTimer.current !== null) window.clearTimeout(seekTimer.current);
    },
    [],
  );

  const timeAt = useCallback(
    (clientX: number) => {
      const rect = trackRef.current?.getBoundingClientRect();
      if (!rect || rect.width === 0) return tl.min;
      return percentToTime(((clientX - rect.left) / rect.width) * 100, tl);
    },
    [tl],
  );

  const beginDrag = (kind: DragKind, e: React.PointerEvent) => {
    e.preventDefault();
    dragRef.current = {
      kind,
      startClientX: e.clientX,
      initialStart: start,
      duration: Math.max(1, end - start),
    };

    // AbortController removes every listener at once, including when the
    // modal closes mid-drag. The original leaked them in that case.
    const ac = new AbortController();
    const { signal } = ac;

    const onMove = (ev: PointerEvent) => {
      const info = dragRef.current;
      if (!info) return;
      const at = timeAt(ev.clientX);

      if (info.kind === 'start') {
        const next = clampStart(at, end, tl);
        setStart(next);
        setHead(next);
        throttledSeek(next);
      } else if (info.kind === 'end') {
        const next = clampEnd(at, start, tl);
        setEnd(next);
        setHead(next);
        throttledSeek(next);
      } else if (info.kind === 'playhead') {
        const next = clampPlayhead(at, tl);
        setHead(next);
        throttledSeek(next);
      } else {
        const rect = trackRef.current?.getBoundingClientRect();
        if (!rect) return;
        const delta = ((ev.clientX - info.startClientX) / rect.width) * tl.span;
        const moved = slideWindow(info.initialStart, info.duration, delta, tl);
        setStart(moved.start);
        setEnd(moved.end);
        setHead(moved.start);
        throttledSeek(moved.start);
      }
    };

    const onUp = () => {
      const info = dragRef.current;
      dragRef.current = null;
      ac.abort();

      // Cancel the pending throttled seek and land exactly.
      if (seekTimer.current !== null) {
        window.clearTimeout(seekTimer.current);
        seekTimer.current = null;
      }
      if (info) seek(info.kind === 'end' ? end : start, false);
    };

    window.addEventListener('pointermove', onMove, { signal });
    window.addEventListener('pointerup', onUp, { signal });
    window.addEventListener('pointercancel', onUp, { signal });
  };

  const reset = () => {
    setStart(clip.start_time);
    setEnd(clip.end_time);
    setHead(clip.start_time);
    seek(clip.start_time, false);
  };

  const apply = () => {
    onApply({ ...clip, start_time: start, end_time: end });
    onClose();
  };

  const changed = start !== clip.start_time || end !== clip.end_time;
  const pct = (time: number) => timeToPercent(time, tl);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t.trimmer.title}
      size="lg"
      footer={
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={reset}
            disabled={!changed}
            icon={<ArrowCounterClockwiseIcon size={13} />}
          >
            {t.trimmer.reset}
          </Button>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>
              {t.common.cancel}
            </Button>
            <Button onClick={apply} disabled={!changed}>
              {t.common.apply}
            </Button>
          </div>
        </div>
      }
    >
      <div className="aspect-video overflow-hidden rounded-[--radius-control] bg-black">
        <div ref={hostRef} className="size-full [&>div]:size-full [&_iframe]:size-full" />
      </div>

      <div className="mt-4 flex items-center justify-between text-xs">
        <span className="tabular font-mono text-ink-dim">
          {formatTimecode(start)} - {formatTimecode(end)}
        </span>
        <span className="tabular font-mono text-ink-faint">
          {t.trimmer.duration}: {Math.round(end - start)}s
        </span>
      </div>

      {/* Click anywhere on the track to scrub. */}
      <div
        ref={trackRef}
        onPointerDown={(e) => {
          if (e.target === trackRef.current) {
            setHead(clampPlayhead(timeAt(e.clientX), tl));
            beginDrag('playhead', e);
          }
        }}
        className="relative mt-2 h-14 touch-none select-none rounded-[--radius-control]
          border border-hairline bg-surface-2"
      >
        {/* The AI's original pick, for reference. */}
        <div
          className="pointer-events-none absolute inset-y-0 bg-teal/15"
          style={{
            left: `${pct(clip.start_time)}%`,
            width: `${pct(clip.end_time) - pct(clip.start_time)}%`,
          }}
        />

        {/* The current selection, draggable as a whole. */}
        <div
          onPointerDown={(e) => {
            e.stopPropagation();
            beginDrag('window', e);
          }}
          className="absolute inset-y-0 cursor-grab border-y-2 border-accent bg-accent/20
            active:cursor-grabbing"
          style={{ left: `${pct(start)}%`, width: `${pct(end) - pct(start)}%` }}
        />

        <button
          type="button"
          aria-label={t.trimmer.startHandle}
          onPointerDown={(e) => {
            e.stopPropagation();
            beginDrag('start', e);
          }}
          className="absolute inset-y-0 w-3 -translate-x-1/2 cursor-ew-resize rounded
            bg-accent"
          style={{ left: `${pct(start)}%` }}
        />
        <button
          type="button"
          aria-label={t.trimmer.endHandle}
          onPointerDown={(e) => {
            e.stopPropagation();
            beginDrag('end', e);
          }}
          className="absolute inset-y-0 w-3 -translate-x-1/2 cursor-ew-resize rounded
            bg-accent"
          style={{ left: `${pct(end)}%` }}
        />

        <div
          className="pointer-events-none absolute inset-y-0 w-0.5 bg-critical"
          style={{ left: `${pct(head)}%` }}
        />
      </div>

      <div className="mt-1.5 flex justify-between text-[0.8rem] text-ink-faint">
        <span className="tabular font-mono">{formatTimecode(tl.min)}</span>
        <span className="tabular font-mono">{formatTimecode(tl.max)}</span>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {[-15, -5, 5, 15].map((d) => (
          <Button
            key={`s${d}`}
            variant="secondary"
            size="sm"
            onClick={() => setStart(clampStart(start + d, end, tl))}
          >
            {t.trimmer.startShift(d)}
          </Button>
        ))}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {[-15, -5, 5, 15].map((d) => (
          <Button
            key={`e${d}`}
            variant="secondary"
            size="sm"
            onClick={() => setEnd(clampEnd(end + d, start, tl))}
          >
            {t.trimmer.endShift(d)}
          </Button>
        ))}
      </div>
    </Modal>
  );
}
