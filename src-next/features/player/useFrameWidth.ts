import { useLayoutEffect, useState, type RefObject } from 'react';

/** Widest the preview frame gets: the old 288px, 15% larger (issue #20). */
export const MAX_FRAME_W = 331;
/** The frame width subtitleFontPx's sizes were tuned for. */
export const SUBTITLE_FRAME_W = 288;

/** The frame for a column `available` px wide: never wider than the column. */
export function frameWidthFor(available: number): number {
  return available > 0 ? Math.min(MAX_FRAME_W, Math.floor(available)) : MAX_FRAME_W;
}

/**
 * Width for the preview frame: MAX_FRAME_W, or the width of `ref` when that
 * is smaller, so the frame never overflows a narrow column (phones).
 */
export function useFrameWidth(ref: RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(MAX_FRAME_W);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    // Measure now, before paint, so a narrow column never shows a frame
    // that is too wide for a moment; then follow resizes.
    setWidth(frameWidthFor(el.getBoundingClientRect().width));
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(([entry]) => setWidth(frameWidthFor(entry.contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);

  return width;
}
