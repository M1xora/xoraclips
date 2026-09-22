import { describe, expect, it } from 'vitest';
import {
  activeWordIndex,
  buildCaptionChunks,
  CAPTION_THEMES,
  chunkAt,
  renderWord,
} from './captions';
import type { TranscriptLine } from '../../lib/types';

const lines: TranscriptLine[] = [
  { start: 10, end: 13, text: 'satu dua tiga' },
  { start: 13, end: 16, text: 'empat lima enam' },
  { start: 16, end: 19, text: 'tujuh delapan sembilan' },
  { start: 40, end: 43, text: 'di luar klip' },
];

describe('buildCaptionChunks', () => {
  it('keeps only words inside the clip', () => {
    const chunks = buildCaptionChunks(lines, 10, 19);
    const words = chunks.flatMap((c) => c.words.map((w) => w.text));
    expect(words).not.toContain('luar');
    expect(words).toContain('satu');
    expect(words).toContain('sembilan');
  });

  it('groups words three at a time', () => {
    const chunks = buildCaptionChunks(lines, 10, 19);
    expect(chunks[0].words).toHaveLength(3);
  });

  it('spreads word timings across the line', () => {
    const [first] = buildCaptionChunks([{ start: 0, end: 3, text: 'a b c' }], 0, 3);
    expect(first.words[0].start).toBeCloseTo(0, 5);
    expect(first.words[1].start).toBeCloseTo(1, 5);
    expect(first.words[2].end).toBeCloseTo(3, 5);
  });

  it('keeps chunk bounds aligned with its words', () => {
    for (const c of buildCaptionChunks(lines, 10, 19)) {
      expect(c.start).toBe(c.words[0].start);
      expect(c.end).toBe(c.words[c.words.length - 1].end);
    }
  });

  it('falls back to the clip transcript when there are no timed lines', () => {
    const chunks = buildCaptionChunks(undefined, 0, 6, 'halo dunia ini contoh');
    expect(chunks.length).toBeGreaterThan(0);
    expect(chunks.flatMap((c) => c.words.map((w) => w.text))).toContain('halo');
  });

  it('spans the whole clip when using the fallback', () => {
    const chunks = buildCaptionChunks(undefined, 0, 6, 'a b c d e f');
    expect(chunks[0].start).toBeCloseTo(0, 5);
    expect(chunks[chunks.length - 1].end).toBeCloseTo(6, 5);
  });

  it('returns nothing when there is no text at all', () => {
    expect(buildCaptionChunks(undefined, 0, 10)).toEqual([]);
    expect(buildCaptionChunks([], 0, 10, '   ')).toEqual([]);
  });

  it('ignores lines that end before the clip starts', () => {
    const chunks = buildCaptionChunks([{ start: 0, end: 5, text: 'lebih awal' }], 10, 20);
    expect(chunks).toEqual([]);
  });

  it('never produces a zero-length word', () => {
    for (const c of buildCaptionChunks(lines, 10, 19)) {
      for (const w of c.words) expect(w.end).toBeGreaterThan(w.start);
    }
  });
});

describe('chunkAt', () => {
  const chunks = buildCaptionChunks(lines, 10, 19);

  it('finds the chunk covering a time', () => {
    expect(chunkAt(chunks, 11)).not.toBeNull();
  });

  it('returns null outside every chunk', () => {
    expect(chunkAt(chunks, 100)).toBeNull();
  });

  it('covers the clip continuously', () => {
    // Gaps would make captions flicker off mid-sentence.
    for (let t = 10.05; t < 18.9; t += 0.5) {
      expect(chunkAt(chunks, t), `no chunk at ${t.toFixed(2)}s`).not.toBeNull();
    }
  });
});

describe('activeWordIndex', () => {
  const [chunk] = buildCaptionChunks([{ start: 0, end: 3, text: 'a b c' }], 0, 3);

  it('tracks the spoken word', () => {
    expect(activeWordIndex(chunk, 0.5)).toBe(0);
    expect(activeWordIndex(chunk, 1.5)).toBe(1);
    expect(activeWordIndex(chunk, 2.5)).toBe(2);
  });

  it('reports -1 before the chunk begins', () => {
    const later = buildCaptionChunks([{ start: 5, end: 8, text: 'x y z' }], 5, 8)[0];
    expect(activeWordIndex(later, 1)).toBe(-1);
  });
});

describe('themes', () => {
  it('covers all seven styles', () => {
    expect(Object.keys(CAPTION_THEMES)).toHaveLength(7);
  });

  it('uses the colours from the original preview', () => {
    expect(CAPTION_THEMES.viral_pop.accent).toBe('#FFE600');
    expect(CAPTION_THEMES.beast_punch.accent).toBe('#00FF66');
    expect(CAPTION_THEMES.cyber_violet.accent).toBe('#D946EF');
    expect(CAPTION_THEMES.fire_red.accent).toBe('#FF2E2E');
    expect(CAPTION_THEMES.electric_cyan.accent).toBe('#00F0FF');
    expect(CAPTION_THEMES.golden_aura.accent).toBe('#FFB800');
  });

  it('keeps clean_minimal free of an accent colour', () => {
    expect(CAPTION_THEMES.clean_minimal.accent).toBe('#FFFFFF');
    expect(CAPTION_THEMES.clean_minimal.glow).toBeUndefined();
  });
});

describe('renderWord', () => {
  it('applies the case option', () => {
    expect(renderWord('halo', 'uppercase')).toBe('HALO');
    expect(renderWord('HALO', 'lowercase')).toBe('halo');
    expect(renderWord('halo', 'capitalize')).toBe('Halo');
  });
});
