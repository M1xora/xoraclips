import { useLayoutEffect, useRef } from 'react';
import { fitTitlePx, TITLE_MIN_PX, TITLE_SAFE_WIDTH } from '../studio/derive';
import { FONT_STACKS } from '../studio/fonts';
import { titleLayout } from './titleLayout';
import type { CaptionFont, FontSizeOption } from '../../lib/types';

interface PreviewTitleProps {
  /** Already cased and broken into lines by formatTitleSmart. */
  text: string;
  sizePreset: FontSizeOption;
  /** The caption font: the renderer draws the title in it too. */
  font: CaptionFont;
  /** Export pixels to preview pixels. */
  scale: number;
  topPercent: number;
}

/**
 * The hook title over the preview, drawn the way the export draws it: the
 * renderer's size for the preset, font and line count, its line breaks,
 * its outline, and a shrink to fit only where the renderer shrinks (emoji
 * titles). A plain title that is too wide overflows here as it is cut off
 * in the video.
 */
export function PreviewTitle({ text, sizePreset, font, scale, topPercent }: PreviewTitleProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const layout = titleLayout(text, sizePreset, font);
  const basePx = layout.emPx * scale;

  // Emoji titles: measure at the full size and shrink if too wide, before
  // paint. Measured again once web fonts load, since widths change then.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || !layout.png) return;
    const fit = () => {
      el.style.fontSize = `${basePx}px`;
      const widest = el.getBoundingClientRect().width;
      el.style.fontSize = `${fitTitlePx(basePx, widest, TITLE_SAFE_WIDTH * scale, TITLE_MIN_PX * scale)}px`;
    };
    fit();
    let live = true;
    document.fonts?.ready.then(() => live && fit());
    return () => {
      live = false;
    };
  }, [text, basePx, scale, layout.png]);

  const outline = layout.outlinePx * scale;
  const shadow = layout.shadowPx * scale;

  return (
    <div
      className="pointer-events-none absolute inset-x-0 text-center"
      style={{ top: `${topPercent}%`, paddingTop: layout.topShiftPx * scale }}
    >
      <span
        ref={ref}
        className="inline-block font-extrabold text-white"
        style={{
          fontFamily: FONT_STACKS[font],
          fontSize: `${basePx}px`,
          lineHeight: `${layout.lineStepPx * scale}px`,
          // The renderer's line breaks, and no others.
          whiteSpace: 'pre',
          // A centred stroke of twice the width leaves the outline's width outside.
          WebkitTextStroke: `${outline * 2}px #000`,
          paintOrder: 'stroke fill',
          textShadow: `${shadow}px ${shadow}px 0 #000`,
        }}
      >
        {text}
      </span>
    </div>
  );
}
