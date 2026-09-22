import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { HeatmapPoint, ViralClip } from '../../lib/types';
import { formatTimecode } from '../../lib/format';

const HEIGHT = 70;
const PAD_TOP = 15;
const CHART_H = 50;

interface HeatmapTimelineProps {
  duration: number;
  heatmap: HeatmapPoint[];
  currentTime: number;
  activeClip?: ViralClip | null;
  onSeek: (seconds: number) => void;
  label: string;
  emptyLabel: string;
}

/**
 * Audience retention curve with a playhead and the active clip's range.
 *
 * Adds what the previous version lacked: it is a real slider to assistive
 * tech, and arrow keys scrub. Before, it was a bare SVG with no role, no
 * labels and no keyboard path at all.
 */
export function HeatmapTimeline({
  duration,
  heatmap,
  currentTime,
  activeClip,
  onSeek,
  label,
  emptyLabel,
}: HeatmapTimelineProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [width, setWidth] = useState(600);
  const [hover, setHover] = useState<{ x: number; time: number; value: number } | null>(null);

  // Track the real rendered width so the curve fills the panel.
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => {
      const w = entry.contentRect.width;
      if (w > 0) setWidth(w);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // Points are spaced by index, matching how the backend returns them.
  const coords = useMemo(() => {
    if (heatmap.length === 0) return [];
    const lastIndex = Math.max(1, heatmap.length - 1);
    return heatmap.map((point, i) => ({
      x: (i / lastIndex) * width,
      y: PAD_TOP + CHART_H - point.value * CHART_H,
      value: point.value,
      time: (point.start_time + point.end_time) / 2,
    }));
  }, [heatmap, width]);

  const linePath = useMemo(() => coords.map((c) => `${c.x},${c.y}`).join(' '), [coords]);

  const areaPath = useMemo(() => {
    if (coords.length === 0) return '';
    return `M 0,${HEIGHT} L ${linePath} L ${width},${HEIGHT} Z`;
  }, [coords, linePath, width]);

  const timeToX = useCallback(
    (t: number) => (duration > 0 ? (t / duration) * width : 0),
    [duration, width],
  );

  const seekFromX = useCallback(
    (clientX: number) => {
      const rect = svgRef.current?.getBoundingClientRect();
      if (!rect || rect.width === 0) return;
      const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
      onSeek(ratio * duration);
    },
    [duration, onSeek],
  );

  const onKeyDown = (e: React.KeyboardEvent) => {
    const step = e.shiftKey ? 30 : 5;
    if (e.key === 'ArrowRight') {
      e.preventDefault();
      onSeek(Math.min(duration, currentTime + step));
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      onSeek(Math.max(0, currentTime - step));
    } else if (e.key === 'Home') {
      e.preventDefault();
      onSeek(0);
    } else if (e.key === 'End') {
      e.preventDefault();
      onSeek(duration);
    }
  };

  const playheadX = timeToX(currentTime);

  return (
    <div className="relative">
      <div className="mb-1.5 flex items-baseline justify-between gap-2">
        <span className="text-xs font-medium text-ink-dim">
          {label}
          {heatmap.length === 0 && (
            <span className="ml-2 text-ink-faint">({emptyLabel})</span>
          )}
        </span>
        <span className="tabular font-mono text-[0.8rem] text-ink-faint">
          {formatTimecode(currentTime)} / {formatTimecode(duration)}
        </span>
      </div>

      <svg
        ref={svgRef}
        width="100%"
        height={HEIGHT}
        role="slider"
        tabIndex={0}
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={Math.round(duration)}
        aria-valuenow={Math.round(currentTime)}
        aria-valuetext={formatTimecode(currentTime)}
        onKeyDown={onKeyDown}
        onClick={(e) => seekFromX(e.clientX)}
        onMouseMove={(e) => {
          const rect = svgRef.current?.getBoundingClientRect();
          if (!rect || coords.length === 0) return;
          const x = e.clientX - rect.left;
          const time = (x / rect.width) * duration;
          const nearest = coords.reduce((best, c) =>
            Math.abs(c.time - time) < Math.abs(best.time - time) ? c : best,
          );
          setHover({ x, time, value: nearest.value });
        }}
        onMouseLeave={() => setHover(null)}
        className="cursor-pointer touch-none"
      >
        <defs>
          <linearGradient id="heat-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-accent)" stopOpacity="0.35" />
            <stop offset="100%" stopColor="var(--color-accent)" stopOpacity="0" />
          </linearGradient>
        </defs>

        {coords.length === 0 ? (
          <line
            x1="0"
            y1={HEIGHT - 20}
            x2={width}
            y2={HEIGHT - 20}
            stroke="var(--color-hairline)"
            strokeWidth="1.5"
            strokeDasharray="4,4"
          />
        ) : (
          <>
            <path d={areaPath} fill="url(#heat-fill)" />
            <polyline
              points={linePath}
              fill="none"
              stroke="var(--color-accent)"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </>
        )}

        {activeClip && duration > 0 && (
          <rect
            x={timeToX(activeClip.start_time)}
            y={PAD_TOP - 5}
            width={Math.max(2, timeToX(activeClip.end_time) - timeToX(activeClip.start_time))}
            height={CHART_H + 10}
            rx="3"
            fill="var(--color-teal)"
            fillOpacity="0.16"
            stroke="var(--color-teal)"
            strokeWidth="1"
            strokeDasharray="3,3"
          />
        )}

        {duration > 0 && (
          <line
            x1={playheadX}
            y1="0"
            x2={playheadX}
            y2={HEIGHT}
            stroke="var(--color-ink)"
            strokeWidth="1.5"
          />
        )}

        {hover && (
          <line
            x1={hover.x}
            y1="0"
            x2={hover.x}
            y2={HEIGHT}
            stroke="var(--color-ink-faint)"
            strokeWidth="1"
            strokeDasharray="2,2"
          />
        )}
      </svg>

      {hover && (
        <div
          className="panel pointer-events-none absolute -top-1 z-[--z-overlay] px-2 py-1"
          style={{ left: Math.min(width - 90, Math.max(0, hover.x - 45)) }}
        >
          <span className="tabular font-mono text-[0.8rem]">
            {formatTimecode(hover.time)} · {Math.round(hover.value * 100)}%
          </span>
        </div>
      )}
    </div>
  );
}
