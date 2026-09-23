import { useLayoutEffect, useRef } from 'react';
import {
  fitTitlePx,
  TITLE_LINE_STEP,
  TITLE_MIN_PX,
  TITLE_SAFE_WIDTH,
  titleExportPx,
} from '../studio/derive';
import type { FontSizeOption } from '../../lib/types';

interface PreviewTitleProps {
  /** Already cased and broken into lines by formatTitleSmart. */
  text: string;
  lineCount: number;
  sizePreset: FontSizeOption;
  /** Export pixels to preview pixels. */
  scale: number;
  topPercent: number;
}

/**
 * The hook title over the preview, sized like the export (issue #19): the
 * renderer's font size for the preset and line count, its line breaks, and
 * the same shrink when the widest line would run past the safe width.
 */
export function PreviewTitle({ text, lineCount, sizePreset, scale, topPercent }: PreviewTitleProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const basePx = titleExportPx(sizePreset, lineCount) * scale;

  // Measure at the full size, then shrink if it is too wide. Done on the DOM
  // before paint, so the too-wide frame is never shown.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.fontSize = `${basePx}px`;
    const widest = el.getBoundingClientRect().width;
    const fitted = fitTitlePx(basePx, widest, TITLE_SAFE_WIDTH * scale, TITLE_MIN_PX * scale);
    el.style.fontSize = `${fitted}px`;
  }, [text, basePx, scale]);

  return (
    <div
      className="pointer-events-none absolute inset-x-0 text-center"
      style={{ top: `${topPercent}%` }}
    >
      <span
        ref={ref}
        className="inline-block font-display font-extrabold text-white"
        style={{
          fontSize: `${basePx}px`,
          lineHeight: TITLE_LINE_STEP,
          // The renderer's line breaks, and no others.
          whiteSpace: 'pre',
          textShadow: '0 1px 3px rgba(0,0,0,.95), 0 0 6px rgba(0,0,0,.8)',
        }}
      >
        {text}
      </span>
    </div>
  );
}
