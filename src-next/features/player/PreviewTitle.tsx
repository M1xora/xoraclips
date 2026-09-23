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

type Layout = ReturnType<typeof titleLayout>;

function sizeStyles(layout: Layout, scale: number) {
  const outline = layout.outlinePx * scale;
  const shadow = layout.shadowPx * scale;
  return {
    paddingTop: `${layout.topShiftPx * scale}px`,
    fontSize: `${layout.emPx * scale}px`,
    lineHeight: `${layout.lineStepPx * scale}px`,
    // A centred stroke of twice the width leaves the outline's width outside.
    stroke: `${outline * 2}px #000`,
    shadow: `${shadow}px ${shadow}px 0 #000`,
  };
}

/**
 * The hook title over the preview, drawn the way the export draws it: the
 * renderer's size for the preset, font and line count, its line breaks,
 * its outline, and a shrink to fit only where the renderer shrinks (emoji
 * titles). A plain title that is too wide overflows both edges here, as it
 * is cut off on both sides in the video.
 */
export function PreviewTitle({ text, sizePreset, font, scale, topPercent }: PreviewTitleProps) {
  const boxRef = useRef<HTMLDivElement>(null);
  const textRef = useRef<HTMLSpanElement>(null);
  const layout = titleLayout(text, sizePreset, font);
  const styles = sizeStyles(layout, scale);

  // Emoji titles: measure at the full size and, if too wide, shrink the way
  // PIL does, in export pixels, recomputing line step, stroke and shadow
  // from the new size. Written to the DOM before paint, so every value is
  // set on each run (React leaves unchanged props alone). Measured again
  // once web fonts have loaded, since widths change then.
  useLayoutEffect(() => {
    const box = boxRef.current;
    const span = textRef.current;
    if (!box || !span) return;
    const apply = (s: ReturnType<typeof sizeStyles>) => {
      box.style.paddingTop = s.paddingTop;
      span.style.fontSize = s.fontSize;
      span.style.lineHeight = s.lineHeight;
      span.style.setProperty('-webkit-text-stroke', s.stroke);
      span.style.textShadow = s.shadow;
    };
    const full = titleLayout(text, sizePreset, font);
    const fit = () => {
      apply(sizeStyles(full, scale));
      if (!full.png) return;
      const widestExport = span.getBoundingClientRect().width / scale;
      const size = fitTitlePx(full.size, widestExport, TITLE_SAFE_WIDTH, TITLE_MIN_PX);
      if (size !== full.size) apply(sizeStyles(titleLayout(text, sizePreset, font, size), scale));
    };
    fit();
    let live = true;
    document.fonts?.ready.then(() => live && fit());
    return () => {
      live = false;
    };
  }, [text, sizePreset, font, scale]);

  return (
    <div
      ref={boxRef}
      // Flex centring overflows both edges; text-align would overflow right.
      className="pointer-events-none absolute inset-x-0 flex justify-center"
      style={{ top: `${topPercent}%`, paddingTop: styles.paddingTop }}
    >
      <span
        ref={textRef}
        className="shrink-0 text-center font-extrabold text-white"
        style={{
          fontFamily: FONT_STACKS[font],
          fontSize: styles.fontSize,
          lineHeight: styles.lineHeight,
          // The renderer's line breaks, and no others.
          whiteSpace: 'pre',
          WebkitTextStroke: styles.stroke,
          paintOrder: 'stroke fill',
          textShadow: styles.shadow,
        }}
      >
        {text}
      </span>
    </div>
  );
}
