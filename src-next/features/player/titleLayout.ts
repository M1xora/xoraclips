import { TITLE_LINE_STEP, titleExportPx } from '../studio/derive';
import { hasEmoji, LIBASS_EM_PER_FONTSIZE } from '../studio/fonts';
import type { CaptionFont, FontSizeOption } from '../../lib/types';

/** What the renderer does with a title (issue #19). */
export function titleLayout(text: string, sizePreset: FontSizeOption, font: CaptionFont) {
  const lineCount = Math.max(1, text.split('\n').length);
  const fontSize = titleExportPx(sizePreset, lineCount);
  // Titles with emoji are drawn by PIL (size = em, shrunk to fit, stroke
  // max(3, 5.5%)); the rest by libass (smaller em per font, never shrunk,
  // TitleStyle outline 4.4 and shadow 2). video_engine.py:640-760, 994.
  const png = hasEmoji(text);
  return {
    png,
    emPx: png ? fontSize : fontSize * LIBASS_EM_PER_FONTSIZE[font],
    lineStepPx: Math.floor(fontSize * TITLE_LINE_STEP),
    // libass puts the top of the font box (as tall as the Fontsize) at the
    // anchor; a CSS line box of lineStep centres that box, so shift it back.
    topShiftPx: (fontSize - Math.floor(fontSize * TITLE_LINE_STEP)) / 2,
    outlinePx: png ? Math.max(3, Math.floor(fontSize * 0.055)) : 4.4,
    shadowPx: png ? Math.max(2, Math.floor(fontSize * 0.025)) : 2,
  };
}
