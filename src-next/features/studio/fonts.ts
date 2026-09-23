import type { CaptionFont } from '../../lib/types';

/** Web-safe stacks for the eight caption fonts the renderer offers. */
export const FONT_STACKS: Record<CaptionFont, string> = {
  Outfit: "'Geist', system-ui, sans-serif",
  Montserrat: "'Geist', system-ui, sans-serif",
  Inter: "'Geist', system-ui, sans-serif",
  Impact: "Impact, 'Arial Black', sans-serif",
  'Bebas Neue': "'Arial Narrow', 'Geist', sans-serif",
  Anton: "'Arial Black', 'Geist', sans-serif",
  Poppins: "'Geist', system-ui, sans-serif",
  'Arial Black': "'Arial Black', sans-serif",
};

/**
 * How big libass really draws a font, per unit of ASS Fontsize: libass
 * scales so that winAscent + winDescent equals the Fontsize, so the em is
 * Fontsize x unitsPerEm / (winAscent + winDescent). Read from the files in
 * backend/fonts (Impact, Arial Black: C:/Windows/Fonts) and checked against
 * a real libass render: cap height 0.57 x Fontsize for Outfit (0.563
 * predicted), 0.50 for Anton (0.496). Issue #19.
 */
export const LIBASS_EM_PER_FONTSIZE: Record<CaptionFont, number> = {
  Outfit: 0.794,
  Montserrat: 0.64,
  Inter: 0.699,
  Impact: 0.82,
  'Bebas Neue': 0.769,
  Anton: 0.577,
  Poppins: 0.568,
  'Arial Black': 0.709,
};

/**
 * The renderer's emoji test, code point for code point (video_engine.py
 * is_emoji_char): a title with any of these is drawn as a PNG by PIL
 * instead of by libass.
 */
const SYMBOL = /^[\p{So}\p{Sk}]$/u;

function isEmojiCodePoint(ch: string): boolean {
  const c = ch.codePointAt(0) ?? 0;
  return (
    (c >= 0x1f000 && c <= 0x1faff) ||
    (c >= 0x2600 && c <= 0x27bf) ||
    (c >= 0x2300 && c <= 0x23ff) ||
    (c >= 0x2b50 && c <= 0x2b55) ||
    c === 0x200d ||
    (c >= 0xfe00 && c <= 0xfe0f) ||
    c === 0x20e3 ||
    SYMBOL.test(ch)
  );
}

export function hasEmoji(text: string): boolean {
  return Array.from(text).some(isEmojiCodePoint);
}
