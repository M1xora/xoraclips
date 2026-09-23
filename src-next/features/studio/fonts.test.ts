import { describe, expect, it } from 'vitest';
import { CAPTION_FONT_FACES, captionFontCss, captionFontUrl } from './captionFonts';
import { FONT_STACKS } from './fonts';

// Fonts libass takes from the system, not from backend/fonts.
const SYSTEM_FONTS = ['Impact', 'Arial Black'];

describe('caption fonts in the preview (#22)', () => {
  it('every face points at a file that exists in backend/fonts', () => {
    expect(CAPTION_FONT_FACES).toHaveLength(6);
    for (const face of CAPTION_FONT_FACES) expect(captionFontUrl(face.file), face.file).toBeTruthy();
  });

  it('declares every face', () => {
    const css = captionFontCss();
    for (const face of CAPTION_FONT_FACES) {
      expect(css).toContain(`font-family:'${face.family}'`);
    }
  });

  it('every caption font is drawn with its own file, first in its stack', () => {
    const families = CAPTION_FONT_FACES.map((f) => f.family);
    for (const [font, stack] of Object.entries(FONT_STACKS)) {
      if (SYSTEM_FONTS.includes(font)) {
        expect(stack.replace(/'/g, '').startsWith(font)).toBe(true);
        continue;
      }
      const first = stack.match(/^'([^']+)'/)?.[1];
      expect(first).toBe(`XC ${font}`);
      expect(families).toContain(first);
    }
  });

  it('only the static-bold files take the whole weight range', () => {
    // Anton and Bebas Neue are 400: the browser synthesises bold, like libass.
    const weight = Object.fromEntries(CAPTION_FONT_FACES.map((f) => [f.file, f.weight]));
    expect(weight['Anton.ttf']).toBe('400');
    expect(weight['Bebas Neue.ttf']).toBe('400');
    expect(weight['Outfit.ttf']).toBe('100 900');
  });
});
