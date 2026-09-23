import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { PreviewTitle } from './PreviewTitle';
import { titleLayout } from './titleLayout';
import { hasEmoji } from '../studio/fonts';
import type { CaptionFont, FontSizeOption } from '../../lib/types';

const SCALE = 288 / 1080;

function render(sizePreset: FontSizeOption, text = 'WINDOWS PANIK', font: CaptionFont = 'Outfit') {
  return renderToStaticMarkup(
    <PreviewTitle text={text} sizePreset={sizePreset} font={font} scale={SCALE} topPercent={14} />,
  );
}

function fontPx(html: string) {
  return Number(html.match(/font-size:([\d.]+)px/)?.[1]);
}

describe('titleLayout (#19): what the renderer does with a title', () => {
  it('libass draws a smaller em than the Fontsize, per font', () => {
    // Measured in a real libass render: Outfit cap height 0.57 x Fontsize,
    // and Outfit caps are 0.709 em, so the em is about 0.80 x Fontsize.
    expect(titleLayout('WINDOWS', 'medium', 'Outfit').emPx).toBeCloseTo(94 * 0.794, 5);
    expect(titleLayout('WINDOWS', 'medium', 'Poppins').emPx).toBeCloseTo(94 * 0.568, 5);
  });

  it('three or more lines use the smaller size', () => {
    expect(titleLayout('A\nB\nC', 'big', 'Outfit').emPx).toBeCloseTo(106 * 0.794, 5);
  });

  it('lines are int(size x 0.86) apart, like line_step', () => {
    expect(titleLayout('A\nB', 'medium', 'Outfit').lineStepPx).toBe(80);
    expect(titleLayout('A\nB', 'big', 'Outfit').lineStepPx).toBe(106);
  });

  it('emoji titles follow the PIL path: em = size, thicker stroke', () => {
    const png = titleLayout('KAGET 😱', 'medium', 'Outfit');
    expect(png.png).toBe(true);
    expect(png.emPx).toBe(94);
    expect(png.outlinePx).toBe(5); // max(3, int(94 * 0.055))
    expect(titleLayout('KAGET', 'medium', 'Outfit').outlinePx).toBe(4.4);
  });

  it('a shrunk PNG title recomputes line step, stroke and shadow from the new size', () => {
    const shrunk = titleLayout('A 😱\nB', 'medium', 'Outfit', 67);
    expect(shrunk.emPx).toBe(67);
    expect(shrunk.lineStepPx).toBe(57); // int(67 * 0.86)
    expect(shrunk.outlinePx).toBe(3); // max(3, int(67 * 0.055))
  });

  it('the font box sits at the anchor: libass box = size, PIL box = size / em ratio', () => {
    const ass = titleLayout('KAGET', 'medium', 'Outfit');
    expect(ass.topShiftPx).toBeCloseTo((94 - 80) / 2, 5);
    const png = titleLayout('KAGET 😱', 'medium', 'Outfit');
    expect(png.topShiftPx).toBeCloseTo((94 / 0.794 - 80) / 2, 5);
  });

  it('recognises emoji the way the renderer does', () => {
    expect(hasEmoji('HEBAT 🔥')).toBe(true);
    expect(hasEmoji('TOP ★')).toBe(true); // So
    expect(hasEmoji('10.000 ORANG, 50%!')).toBe(false);
  });
});

describe('PreviewTitle (#19)', () => {
  it('the size buttons change the preview size, in step with the export', () => {
    const [s, m, b] = (['small', 'medium', 'big'] as const).map((p) => fontPx(render(p)));
    expect(s).toBeCloseTo(68 * 0.794 * SCALE, 5);
    expect(m).toBeCloseTo(94 * 0.794 * SCALE, 5);
    expect(b).toBeCloseTo(124 * 0.794 * SCALE, 5);
  });

  it('keeps the line breaks exactly, with no automatic wrapping', () => {
    const html = render('big', 'WINDOWS PANIK\nKARENA MACBOOK');
    expect(html).toContain('WINDOWS PANIK\nKARENA MACBOOK');
    expect(html).toContain('white-space:pre');
  });

  it('draws in the caption font, which the renderer uses for the title', () => {
    expect(render('medium', 'X', 'Impact')).toContain('font-family:Impact');
  });
});
