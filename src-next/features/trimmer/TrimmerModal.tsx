import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowCounterClockwiseIcon } from '@phosphor-icons/react';
import { Button } from '../../components/ui/Button';
import { Modal } from '../../components/ui/Modal';
import { useYouTubePlayer } from '../../hooks/useYouTubePlayer';
import { formatPreciseTimecode, formatTimecode, parseTimecode } from '../../lib/format';
import { useLanguage } from '../../i18n';
import {
  buildTimeline,
  clampEnd,
  clampPlayhead,
  clampStart,
  lineEdges,
  nudgeEnd,
  nudgeStart,
  percentToTime,
  playbackStretch,
  playedPastEnd,
  slideWindow,
  timeToPercent,
  withEnd,
  withStart,
  type LineEdge,
} from './trimMath';
import type { TranscriptLine, ViralClip } from '../../lib/types';

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
  /** The analysis transcript, for cutting at a line (#56). */
  transcript?: TranscriptLine[];
  onApply: (adjusted: ViralClip) => void;
  onClose: () => void;
}

/**
 * A typed start or end time (#56). Shows the value until edited; Enter or
 * leaving the field applies it, and text that is not a time is dropped.
 */
function TimeField({
  label,
  value,
  onCommit,
}: {
  label: string;
  value: number;
  onCommit: (seconds: number) => void;
}) {
  // The typed text remembers the value it was typed over: once the value
  // changes elsewhere (a handle, a line button), the old text is dropped.
  const [typed, setTyped] = useState<{ text: string; over: number } | null>(null);
  const draft = typed && typed.over === value ? typed.text : null;
  const commit = () => {
    if (draft === null) return;
    const seconds = parseTimecode(draft);
    setTyped(null);
    if (seconds !== null) onCommit(seconds);
  };
  return (
    <label className="flex items-center gap-1.5 text-xs text-ink-faint">
      {label}
      <input
        value={draft ?? formatPreciseTimecode(value)}
        onChange={(e) => setTyped({ text: e.target.value, over: value })}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit();
        }}
        inputMode="decimal"
        spellCheck={false}
        className="tabular h-7 w-24 rounded-[--radius-control] border border-hairline bg-surface-2
          px-2 font-mono text-xs text-ink"
      />
    </label>
  );
}

interface TranscriptLinesProps {
  lines: LineEdge[];
  start: number;
  end: number;
  labels: { title: string; hint: string; setStart: string; setEnd: string };
  onSeek: (time: number) => void;
  onSetStart: (time: number) => void;
  onSetEnd: (time: number) => void;
}

/**
 * The transcript lines around the clip (#56). Memoised: the modal re-renders
 * on every playback poll, and this list only changes with the selection.
 */
const TranscriptLines = memo(function TranscriptLines({
  lines,
  start,
  end,
  labels,
  onSeek,
  onSetStart,
  onSetEnd,
}: TranscriptLinesProps) {
  // Opens scrolled to the clip's own lines, not two minutes before them.
  const listRef = useRef<HTMLOListElement>(null);
  useEffect(() => {
    const list = listRef.current;
    const first = list?.querySelector<HTMLElement>('[data-inside="true"]');
    if (list && first) list.scrollTop = Math.max(0, first.offsetTop - list.clientHeight / 3);
  }, []);

  return (
    <section className="mt-4">
      <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-x-3 text-xs">
        <h3 className="font-medium text-ink-dim">{labels.title}</h3>
        <span className="text-ink-faint">{labels.hint}</span>
      </div>
      <ol
        ref={listRef}
        className="relative max-h-56 divide-y divide-hairline overflow-y-auto
          rounded-[--radius-control] border border-hairline"
      >
        {lines.map((line, i) => {
          const inside = line.start >= start - 0.005 && line.end <= end + 0.005;
          return (
            <li
              key={`${line.start}-${i}`}
              data-inside={inside}
              className={`flex items-center gap-2 px-2.5 py-1 text-xs ${inside ? 'bg-accent/10' : ''}`}
            >
              <button
                type="button"
                onClick={() => onSeek(line.start)}
                className="flex min-w-0 flex-1 items-baseline gap-2 text-left hover:text-ink"
              >
                <span className="tabular shrink-0 font-mono text-ink-faint">
                  {formatTimecode(line.start)}
                </span>
                <span className={inside ? 'text-ink' : 'text-ink-dim'}>{line.text}</span>
              </button>
              <Button variant="ghost" size="sm" onClick={() => onSetStart(line.start)}>
                {labels.setStart}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => onSetEnd(line.end)}>
                {labels.setEnd}
              </Button>
            </li>
          );
        })}
      </ol>
    </section>
  );
});

/** "12.7s": the length to a tenth, since typed and line times are not whole seconds. */
function formatLength(seconds: number): string {
  return `${Math.round(Math.max(0, seconds) * 10) / 10}s`;
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
  transcript,
  onApply,
  onClose,
}: TrimmerModalProps) {
  const { t } = useLanguage();
  const tl = useMemo(
    () => buildTimeline(clip.start_time, clip.end_time, videoDuration),
    [clip.start_time, clip.end_time, videoDuration],
  );

  const [start, setStart] = useState(clip.start_time);
  const [end, setEnd] = useState(clip.end_time);
  const [head, setHead] = useState(clip.start_time);
  const [dragging, setDragging] = useState(false);

  const trackRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<DragInfo | null>(null);
  const seekTimer = useRef<number | null>(null);

  // No `bounds`: that shared hook moves the player back to the start whenever
  // the end changes, which fights dragging the end handle. The stop at the
  // end is done below instead (#56).
  const { hostRef, ready, seek, pause, playing, currentTime } = useYouTubePlayer({
    videoId,
    bounds: null,
    controls: true,
  });

  // Playback that began inside the selection stops at its end and goes back
  // to the start, so the trim can be heard exactly (#56). Playback that began
  // before the selection, and jumps (a line click, YouTube's seek bar, moving
  // the end), are left alone.
  const lastTime = useRef(currentTime);
  const stretch = useRef<number | null>(null);
  useEffect(() => {
    const previous = lastTime.current;
    lastTime.current = currentTime;
    stretch.current = playbackStretch(stretch.current, previous, currentTime, playing);
    if (playing && playedPastEnd(stretch.current, previous, currentTime, start, end)) {
      pause();
      seek(start, false);
    }
  }, [playing, currentTime, start, end, pause, seek]);

  const lines = useMemo(
    () => lineEdges(transcript ?? []).filter((l) => l.end > tl.min && l.start < tl.max),
    [transcript, tl.min, tl.max],
  );

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
    setDragging(true);
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
      setDragging(false);
      ac.abort();

      // Cancel the pending throttled seek and land exactly.
      if (seekTimer.current !== null) {
        window.clearTimeout(seekTimer.current);
        seekTimer.current = null;
      }
      if (info) seek(info.kind === 'end' ? end : info.kind === 'playhead' ? head : start, false);
    };

    window.addEventListener('pointermove', onMove, { signal });
    window.addEventListener('pointerup', onUp, { signal });
    window.addEventListener('pointercancel', onUp, { signal });
  };

  /** A precise edit (typed time or a transcript line), not rounded to seconds. */
  const setRange = useCallback(
    (next: { start: number; end: number }, seekTo: number) => {
      setStart(next.start);
      setEnd(next.end);
      seek(seekTo, false);
    },
    [seek],
  );

  const seekToLine = useCallback((time: number) => seek(time, false), [seek]);
  const startAtLine = useCallback(
    (time: number) => {
      const next = withStart(time, end, tl);
      setRange(next, next.start);
    },
    [end, tl, setRange],
  );
  const endAtLine = useCallback(
    (time: number) => {
      const next = withEnd(time, start, tl);
      setRange(next, next.end);
    },
    [start, tl, setRange],
  );
  const lineLabels = useMemo(
    () => ({
      title: t.trimmer.linesTitle,
      hint: t.trimmer.linesHint,
      setStart: t.trimmer.setStart,
      setEnd: t.trimmer.setEnd,
    }),
    [t],
  );

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
  // The red line is where the video is; while a handle is dragged it follows
  // the pointer, since the player catches up only every 120ms.
  const playhead = dragging || !ready ? head : clampPlayhead(currentTime, tl);

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

      <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-xs">
        <div className="flex flex-wrap items-center gap-3">
          <TimeField
            label={t.trimmer.startTime}
            value={start}
            onCommit={(at) => {
              const next = withStart(at, end, tl);
              setRange(next, next.start);
            }}
          />
          <TimeField
            label={t.trimmer.endTime}
            value={end}
            onCommit={(at) => {
              const next = withEnd(at, start, tl);
              setRange(next, next.end);
            }}
          />
        </div>
        <span className="tabular font-mono text-ink-faint">
          {t.trimmer.duration}: {formatLength(end - start)}
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
          style={{ left: `${pct(playhead)}%` }}
        />
      </div>

      <div className="mt-1.5 flex justify-between text-[0.8rem] text-ink-faint">
        <span className="tabular font-mono">{formatTimecode(tl.min)}</span>
        <span className="tabular font-mono">{formatTimecode(tl.max)}</span>
      </div>

      {/* Nudges keep hundredths set by a typed time or a line (#56). */}
      <div className="mt-3 flex flex-wrap gap-1.5">
        {[-15, -5, 5, 15].map((d) => (
          <Button
            key={`s${d}`}
            variant="secondary"
            size="sm"
            onClick={() => setStart(nudgeStart(start + d, end, tl))}
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
            onClick={() => setEnd(nudgeEnd(end + d, start, tl))}
          >
            {t.trimmer.endShift(d)}
          </Button>
        ))}
      </div>

      {lines.length > 0 && (
        <TranscriptLines
          lines={lines}
          start={start}
          end={end}
          labels={lineLabels}
          onSeek={seekToLine}
          onSetStart={startAtLine}
          onSetEnd={endAtLine}
        />
      )}
    </Modal>
  );
}
