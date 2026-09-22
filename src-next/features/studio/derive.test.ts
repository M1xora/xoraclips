import { describe, expect, it } from 'vitest';
import {
  applyLetterCase,
  formatTitleSmart,
  getCenterBounds,
  getDefaultPositions,
  getDefaultWatermarkConfig,
  getMaxPositions,
  subtitleFontPx,
  titleFontPx,
  watermarkPreset,
} from './derive';
import type { AspectRatioOption, FontSizeOption } from '../../lib/types';

const RATIOS: AspectRatioOption[] = ['9:16', '1:1', '4:3', '16:9'];
const SIZES: FontSizeOption[] = ['small', 'medium', 'big'];

describe('getDefaultPositions', () => {
  // Transcribed from ClipStudioSection.tsx:944-975. The 1:1 subtitleY is
  // 18.0 rather than the original 20.0, which its own ceiling always
  // clamped away.
  const expected: Record<AspectRatioOption, Record<number, [number, number]>> = {
    '9:16': { 1: [17.0, 21.0], 2: [14.5, 21.0], 3: [12.0, 21.0], 4: [12.0, 21.0] },
    '1:1': { 1: [17.0, 18.0], 2: [13.5, 18.0], 3: [11.5, 18.0], 4: [11.5, 18.0] },
    '4:3': { 1: [23.6, 25.0], 2: [19.3, 25.0], 3: [17.3, 25.0], 4: [17.3, 25.0] },
    '16:9': { 1: [28.8, 30.0], 2: [24.5, 30.0], 3: [22.6, 30.0], 4: [22.6, 30.0] },
  };

  for (const ratio of RATIOS) {
    for (const lines of [1, 2, 3, 4]) {
      it(`${ratio} with ${lines} line(s)`, () => {
        const [titleY, subtitleY] = expected[ratio][lines];
        const pos = getDefaultPositions(ratio, lines);
        expect(pos.titleY).toBe(titleY);
        expect(pos.subtitleY).toBe(subtitleY);
        expect(pos.subCenterY).toBe(50);
      });
    }
  }
});

describe('getMaxPositions', () => {
  // From ClipStudioSection.tsx:980-1003. Four steps here against three in
  // getDefaultPositions; the ladders are deliberately not parallel.
  const expected: Record<AspectRatioOption, Record<number, [number, number]>> = {
    '9:16': { 1: [45.0, 45.0], 2: [45.0, 45.0], 3: [45.0, 45.0], 4: [45.0, 45.0] },
    '1:1': { 1: [18.0, 18.0], 2: [15.0, 18.0], 3: [13.5, 18.0], 4: [12.5, 18.0] },
    '4:3': { 1: [25.0, 25.0], 2: [22.0, 25.0], 3: [20.5, 25.0], 4: [19.5, 25.0] },
    '16:9': { 1: [30.0, 30.5], 2: [27.0, 30.5], 3: [25.5, 30.5], 4: [24.5, 30.5] },
  };

  for (const ratio of RATIOS) {
    for (const lines of [1, 2, 3, 4]) {
      it(`${ratio} with ${lines} line(s)`, () => {
        const [maxTitleY, maxSubY] = expected[ratio][lines];
        const max = getMaxPositions(ratio, lines);
        expect(max.maxTitleY).toBe(maxTitleY);
        expect(max.maxSubY).toBe(maxSubY);
      });
    }
  }

  it('keeps every default inside its own ceiling', () => {
    // The check that caught the 1:1 subtitle bug.
    for (const ratio of RATIOS) {
      for (const lines of [1, 2, 3, 4]) {
        const def = getDefaultPositions(ratio, lines);
        const max = getMaxPositions(ratio, lines);
        expect(def.titleY, `${ratio}/${lines} titleY`).toBeLessThanOrEqual(max.maxTitleY);
        expect(def.subtitleY, `${ratio}/${lines} subtitleY`).toBeLessThanOrEqual(max.maxSubY);
      }
    }
  });
});

describe('getCenterBounds', () => {
  it.each([
    ['16:9', 38, 62],
    ['4:3', 34, 66],
    ['1:1', 28, 72],
    ['9:16', 25, 75],
  ] as const)('%s spans %d to %d', (ratio, min, max) => {
    expect(getCenterBounds(ratio)).toEqual({ min, max });
  });

  it('always contains dead centre', () => {
    for (const ratio of RATIOS) {
      const { min, max } = getCenterBounds(ratio);
      expect(min).toBeLessThan(50);
      expect(max).toBeGreaterThan(50);
    }
  });
});

describe('applyLetterCase', () => {
  it('uppercases', () => {
    expect(applyLetterCase('hello world', 'uppercase')).toBe('HELLO WORLD');
  });
  it('lowercases', () => {
    expect(applyLetterCase('HELLO WORLD', 'lowercase')).toBe('hello world');
  });
  it('capitalises each word', () => {
    expect(applyLetterCase('hello world', 'capitalize')).toBe('Hello World');
  });
  it('capitalises after punctuation, matching the original regex', () => {
    expect(applyLetterCase("it's here", 'capitalize')).toBe("It'S Here");
  });
});

describe('formatTitleSmart', () => {
  it('returns one line for empty input', () => {
    expect(formatTitleSmart('', 'uppercase', 'medium')).toEqual({ formatted: '', lineCount: 1 });
  });

  it('keeps a single word on one line however long', () => {
    const r = formatTitleSmart('supercalifragilisticexpialidocious', 'uppercase', 'big');
    expect(r.lineCount).toBe(1);
  });

  it('honours manual line breaks instead of wrapping', () => {
    const r = formatTitleSmart('line one\nline two\nline three', 'uppercase', 'medium');
    expect(r.lineCount).toBe(3);
    expect(r.formatted.split('\n')).toHaveLength(3);
  });

  it('drops blank manual lines', () => {
    const r = formatTitleSmart('one\n\n\ntwo', 'uppercase', 'medium');
    expect(r.lineCount).toBe(2);
  });

  it('never exceeds four lines', () => {
    const long = 'word '.repeat(60).trim();
    for (const size of SIZES) {
      expect(formatTitleSmart(long, 'uppercase', size).lineCount).toBeLessThanOrEqual(4);
    }
  });

  // maxSingleLen is 24/19/13 for small/medium/big, matching
  // video_engine.py:699-704, so the preset drives the line count.
  it('wraps a 20-character title only at the big preset', () => {
    const title = 'Growth hacking tips!'; // 20 chars
    expect(formatTitleSmart(title, 'uppercase', 'small').lineCount).toBe(1);
    expect(formatTitleSmart(title, 'uppercase', 'medium').lineCount).toBeGreaterThan(1);
    expect(formatTitleSmart(title, 'uppercase', 'big').lineCount).toBeGreaterThan(1);
  });

  it('gives big no fewer lines than small for the same title', () => {
    const title = 'This is a reasonably long clip title for testing';
    const small = formatTitleSmart(title, 'uppercase', 'small').lineCount;
    const big = formatTitleSmart(title, 'uppercase', 'big').lineCount;
    expect(big).toBeGreaterThanOrEqual(small);
  });

  it('keeps every word, in order', () => {
    const title = 'the quick brown fox jumps over the lazy dog';
    const r = formatTitleSmart(title, 'lowercase', 'medium');
    expect(r.formatted.split('\n').join(' ')).toBe(title);
  });

  it('reports a line count matching the formatted text', () => {
    const title = 'Another title that should wrap across several lines here';
    for (const size of SIZES) {
      const r = formatTitleSmart(title, 'uppercase', size);
      expect(r.lineCount).toBe(r.formatted.split('\n').length);
    }
  });

  it('is deterministic', () => {
    const title = 'Repeatable output for the same input';
    const a = formatTitleSmart(title, 'uppercase', 'medium');
    const b = formatTitleSmart(title, 'uppercase', 'medium');
    expect(a).toEqual(b);
  });
});

describe('preview font sizes', () => {
  it.each([
    ['small', 1, 16.5],
    ['small', 3, 14],
    ['medium', 1, 21],
    ['medium', 3, 18],
    ['big', 1, 26],
    ['big', 3, 22.5],
  ] as const)('title %s with %d line(s) is %dpx', (preset, lines, px) => {
    expect(titleFontPx(preset, lines)).toBe(px);
  });

  it.each([
    ['small', 17],
    ['medium', 20.5],
    ['big', 25],
  ] as const)('subtitle %s is %dpx', (preset, px) => {
    expect(subtitleFontPx(preset)).toBe(px);
  });
});

describe('watermark', () => {
  it('defaults differ between image and text', () => {
    expect(getDefaultWatermarkConfig('image')).toEqual({ size: 20, opacity: 80, x: 88, y: 8 });
    expect(getDefaultWatermarkConfig('text')).toEqual({ size: 20, opacity: 80, x: 50, y: 92 });
  });

  it('insets corner presets by half the watermark width', () => {
    expect(watermarkPreset('tl', 20)).toEqual({ x: 12, y: 8 });
    expect(watermarkPreset('br', 20)).toEqual({ x: 88, y: 92 });
  });

  it('collapses both corners to centre at extreme sizes', () => {
    // Documents existing behaviour rather than endorsing it.
    expect(watermarkPreset('tl', 500).x).toBe(50);
    expect(watermarkPreset('tr', 500).x).toBe(50);
  });

  it('keeps centre presets centred at any size', () => {
    for (const size of [10, 100, 500]) {
      expect(watermarkPreset('c', size)).toEqual({ x: 50, y: 50 });
    }
  });
});
