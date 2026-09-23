import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { PreviewTitle } from './PreviewTitle';
import type { FontSizeOption } from '../../lib/types';

const SCALE = 288 / 1080;

function render(sizePreset: FontSizeOption, text = 'WINDOWS PANIK', lineCount = 1) {
  return renderToStaticMarkup(
    <PreviewTitle text={text} lineCount={lineCount} sizePreset={sizePreset} scale={SCALE} topPercent={14} />,
  );
}

function fontPx(html: string) {
  return Number(html.match(/font-size:([\d.]+)px/)?.[1]);
}

describe('PreviewTitle (#19)', () => {
  it('the size buttons change the preview size, in step with the export', () => {
    expect(fontPx(render('small'))).toBeCloseTo(68 * SCALE, 5);
    expect(fontPx(render('medium'))).toBeCloseTo(94 * SCALE, 5);
    expect(fontPx(render('big'))).toBeCloseTo(124 * SCALE, 5);
  });

  it('three or more lines use the smaller size, like the export', () => {
    expect(fontPx(render('medium', 'A\nB\nC', 3))).toBeCloseTo(82 * SCALE, 5);
  });

  it('keeps the line breaks exactly, with no automatic wrapping', () => {
    const html = render('big', 'WINDOWS PANIK\nKARENA MACBOOK', 2);
    expect(html).toContain('WINDOWS PANIK\nKARENA MACBOOK');
    expect(html).toContain('white-space:pre');
  });
});
