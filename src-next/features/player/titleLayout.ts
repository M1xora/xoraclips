import { TITLE_LINE_STEP, titleExportPx } from '../studio/derive';
import { hasEmoji, LIBASS_EM_PER_FONTSIZE } from '../studio/fonts';
import type { CaptionFont, FontSizeOption } from '../../lib/types';

/**
 * What the renderer does with a title (issue #19), in export pixels.
 *
 * Titles with emoji are drawn by PIL: em = size, shrunk to fit, stroke
 * max(3, int(5.5%)), shadow max(2, int(2.5%)). The rest by libass: a
 * smaller em per font, never shrunk, TitleStyle outline 4.4 and shadow 2.
 * Both step lines by int(size x 0.86). video_engine.py:640-760, 994.
 *
 * `fontSize` overrides the preset's size, for a PNG title that was shrunk.
 */
export function titleLayout(text: string, sizePreset: FontSizeOption, font: CaptionFont, fontSize?: number) {
  const lineCount = Math.max(1, text.split('\n').length);
  const size = fontSize ?? titleExportPx(sizePreset, lineCount);
  const png = hasEmoji(text);
  const emPerSize = LIBASS_EM_PER_FONTSIZE[font];
  const emPx = png ? size : size * emPerSize;
  const lineStepPx = Math.floor(size * TITLE_LINE_STEP);
  // Both renderers put the top of the font box at the line's anchor. The
  // box is winAscent + winDescent tall: the Fontsize itself for libass,
  // size / emPerSize for PIL. A CSS line box of lineStep centres it.
  const boxPx = emPx / emPerSize;
  return {
    png,
    size,
    emPx,
    lineStepPx,
    topShiftPx: (boxPx - lineStepPx) / 2,
    outlinePx: png ? Math.max(3, Math.floor(size * 0.055)) : 4.4,
    shadowPx: png ? Math.max(2, Math.floor(size * 0.025)) : 2,
  };
}
