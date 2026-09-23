import type {
  AspectRatioOption,
  FontSizeOption,
  TextCaseOption,
} from '../../lib/types';

/**
 * Pure layout maths for the studio.
 *
 * Every table here is copied verbatim from ClipStudioSection.tsx:864-1010,
 * because these numbers have to agree with what the renderer does in
 * backend/video_engine.py. A cleaner-looking rewrite that shifts a value by
 * a point produces a video whose title sits somewhere other than the
 * preview promised, and nothing catches it but the eye, after the render.
 */

export interface Positions {
  titleY: number;
  subtitleY: number;
  subCenterY: number;
}

export interface MaxPositions {
  maxTitleY: number;
  maxSubY: number;
}

export interface CenterBounds {
  min: number;
  max: number;
}

/**
 * Starting positions per aspect ratio and title line count.
 *
 * One deliberate change from the original: 1:1 subtitleY was 20.0 while its
 * own ceiling is 18.0, so the default was always clamped away. It is 18.0
 * here. The rendered result is identical; the slider now shows the truth.
 */
export function getDefaultPositions(ratio: AspectRatioOption, lines: number): Positions {
  if (ratio === '1:1') {
    return {
      titleY: lines >= 3 ? 11.5 : lines === 2 ? 13.5 : 17.0,
      subtitleY: 18.0,
      subCenterY: 50,
    };
  }
  if (ratio === '4:3') {
    return {
      titleY: lines >= 3 ? 17.3 : lines === 2 ? 19.3 : 23.6,
      subtitleY: 25.0,
      subCenterY: 50,
    };
  }
  if (ratio === '16:9') {
    return {
      titleY: lines >= 3 ? 22.6 : lines === 2 ? 24.5 : 28.8,
      subtitleY: 30.0,
      subCenterY: 50,
    };
  }
  // 9:16 fullscreen
  return {
    titleY: lines >= 3 ? 12.0 : lines === 2 ? 14.5 : 17.0,
    subtitleY: 21.0,
    subCenterY: 50,
  };
}

/**
 * Hard ceilings so a slider cannot push text into the content box.
 *
 * Note the ladder here has four steps (>=4, 3, 2, else) while
 * getDefaultPositions has three (>=3, 2, else). They are not parallel, and
 * lining them up would change behaviour.
 */
export function getMaxPositions(ratio: AspectRatioOption, lines: number): MaxPositions {
  if (ratio === '1:1') {
    return {
      maxTitleY: lines >= 4 ? 12.5 : lines === 3 ? 13.5 : lines === 2 ? 15.0 : 18.0,
      maxSubY: 18.0,
    };
  }
  if (ratio === '4:3') {
    return {
      maxTitleY: lines >= 4 ? 19.5 : lines === 3 ? 20.5 : lines === 2 ? 22.0 : 25.0,
      maxSubY: 25.0,
    };
  }
  if (ratio === '16:9') {
    return {
      maxTitleY: lines >= 4 ? 24.5 : lines === 3 ? 25.5 : lines === 2 ? 27.0 : 30.0,
      maxSubY: 30.5,
    };
  }
  return { maxTitleY: 45.0, maxSubY: 45.0 };
}

/** Range the centre-mode subtitle may occupy, per ratio. */
export function getCenterBounds(ratio: AspectRatioOption): CenterBounds {
  if (ratio === '16:9') return { min: 38, max: 62 };
  if (ratio === '4:3') return { min: 34, max: 66 };
  if (ratio === '1:1') return { min: 28, max: 72 };
  return { min: 25, max: 75 };
}

export interface WatermarkConfig {
  size: number;
  opacity: number;
  x: number;
  y: number;
}

export function getDefaultWatermarkConfig(type: 'image' | 'text'): WatermarkConfig {
  return type === 'text'
    ? { size: 20, opacity: 80, x: 50, y: 92 }
    : { size: 20, opacity: 80, x: 88, y: 8 };
}

/** Upper/lower case transform applied to titles and captions. */
export function applyLetterCase(text: string, style: TextCaseOption): string {
  if (style === 'uppercase') return text.toUpperCase();
  if (style === 'lowercase') return text.toLowerCase();
  return text.toLowerCase().replace(/(?:^|\s|\b)\w/g, (c) => c.toUpperCase());
}

/** Characters as Python's len() counts them: an emoji is one, not two. */
function charCount(text: string): number {
  return Array.from(text).length;
}

/**
 * Wraps a title across up to four lines.
 *
 * Copied verbatim, including two things that look like slips and are load
 * bearing: the check reads `currentLen + wLen` while the accumulator
 * adds `wLen + 1`, and the threshold is scaled by 1.15. Lengths are code
 * points, like Python's len(), so an emoji counts once (#19). The returned
 * lineCount feeds back into title position and font size, so a different
 * split moves the whole layout.
 *
 * `maxSingleLen` matches video_engine.py:699-704, which is why the font
 * size preset changes the line count.
 */
export function formatTitleSmart(
  rawText: string,
  style: TextCaseOption,
  sizePreset: FontSizeOption,
): { formatted: string; lineCount: number } {
  const raw = rawText.trim();
  if (!raw) return { formatted: '', lineCount: 1 };

  const cased = applyLetterCase(raw, style);

  // Manual line breaks win over automatic wrapping.
  if (cased.includes('\n')) {
    const manualLines = cased
      .split('\n')
      .map((l) => l.trim())
      .filter(Boolean);
    return {
      formatted: manualLines.join('\n'),
      lineCount: Math.max(1, manualLines.length),
    };
  }

  const words = cased.split(/\s+/).filter(Boolean);
  const maxSingleLen = sizePreset === 'small' ? 24 : sizePreset === 'big' ? 13 : 19;
  if (words.length <= 1 || charCount(cased) <= maxSingleLen) {
    return { formatted: cased, lineCount: 1 };
  }

  const totalLen = charCount(cased);
  const targetLines = Math.min(4, Math.max(2, Math.ceil(totalLen / maxSingleLen)));
  const targetPerLine = totalLen / targetLines;

  const lines: string[] = [];
  let currentLine: string[] = [];
  let currentLen = 0;

  for (let i = 0; i < words.length; i++) {
    const w = words[i];
    const wLen = charCount(w);
    const remainingWords = words.length - i;
    const remainingLines = targetLines - lines.length;

    if (
      remainingLines > 1 &&
      currentLine.length > 0 &&
      (currentLen + wLen > targetPerLine * 1.15 || remainingWords <= remainingLines - 1)
    ) {
      lines.push(currentLine.join(' '));
      currentLine = [w];
      currentLen = wLen;
    } else {
      currentLine.push(w);
      currentLen += wLen + 1;
    }
  }

  if (currentLine.length > 0) lines.push(currentLine.join(' '));

  return { formatted: lines.join('\n'), lineCount: Math.max(1, lines.length) };
}

/**
 * Title font size in export pixels (1080-wide canvas), the numbers the
 * renderer uses (video_engine.py:666-671). Multiply by the preview scale.
 */
export function titleExportPx(preset: FontSizeOption, lineCount: number): number {
  if (preset === 'small') return lineCount >= 3 ? 58 : 68;
  if (preset === 'big') return lineCount >= 3 ? 106 : 124;
  return lineCount >= 3 ? 82 : 94;
}

/** Widest a title line may be, and the smallest it may shrink to (export px). */
export const TITLE_SAFE_WIDTH = 1010;
export const TITLE_MIN_PX = 40;
/** Distance between title lines, relative to the font size (line_step). */
export const TITLE_LINE_STEP = 0.86;

/**
 * Shrinks a title whose widest line is wider than the safe width, the way
 * the renderer does (video_engine.py:692-697). Units only need to agree.
 */
export function fitTitlePx(sizePx: number, widestLinePx: number, maxWidthPx: number, minPx: number): number {
  if (widestLinePx <= maxWidthPx || widestLinePx <= 0) return sizePx;
  return Math.max(minPx, Math.floor(sizePx * (maxWidthPx / widestLinePx)));
}

/**
 * Subtitle Fontsize in export pixels, the renderer's numbers
 * (video_engine.py:851-856). Like the title, libass draws a smaller em than
 * this: multiply by LIBASS_EM_PER_FONTSIZE for the font, then the scale.
 */
export function subtitleExportPx(preset: FontSizeOption): number {
  if (preset === 'small') return 65;
  if (preset === 'big') return 94;
  return 78;
}

/** Corner and edge presets for the watermark, in percent. */
export function watermarkPreset(
  corner: 'tl' | 'tc' | 'tr' | 'c' | 'bl' | 'bc' | 'br',
  size: number,
): { x: number; y: number } {
  // The horizontal inset depends on the current size, so a preset is not
  // a fixed coordinate. Matches ClipStudioSection.tsx:825-862.
  const halfW = Math.round(size / 2);
  const leftX = Math.max(4, Math.min(50, halfW + 2));
  const rightX = Math.min(96, Math.max(50, 100 - halfW - 2));

  switch (corner) {
    case 'tl':
      return { x: leftX, y: 8 };
    case 'tc':
      return { x: 50, y: 8 };
    case 'tr':
      return { x: rightX, y: 8 };
    case 'c':
      return { x: 50, y: 50 };
    case 'bl':
      return { x: leftX, y: 92 };
    case 'bc':
      return { x: 50, y: 92 };
    case 'br':
      return { x: rightX, y: 92 };
  }
}
