import { describe, expect, it } from 'vitest';
import { activeWordIndex, CAPTION_THEMES, chunkAt, chunksFromApi } from './captions';
import type { ApiCaptionChunk } from '../../api/client';
import ted from './__fixtures__/caption-chunks.ted.json';

// Real backend output (backend/tests keeps this file in sync).
const apiChunks = ted.chunks as ApiCaptionChunk[];
const chunks = chunksFromApi(apiChunks, ted.clip_start);

describe('chunksFromApi', () => {
  it('moves every time onto the source timeline without changing text', () => {
    expect(chunks).toHaveLength(apiChunks.length);
    chunks.forEach((c, i) => {
      const api = apiChunks[i];
      expect(c.start).toBeCloseTo(ted.clip_start + api.start, 9);
      expect(c.end).toBeCloseTo(ted.clip_start + api.end, 9);
      expect(c.words.map((w) => w.text)).toEqual(api.words.map((w) => w.text));
      c.words.forEach((w, j) => {
        expect(w.start).toBeCloseTo(ted.clip_start + api.words[j].start, 9);
        expect(w.end).toBeCloseTo(ted.clip_start + api.words[j].end, 9);
      });
    });
  });

  it('keeps the backend word order', () => {
    expect(chunks.flatMap((c) => c.words.map((w) => w.text)).join(' ')).toBe(
      apiChunks.map((c) => c.text).join(' '),
    );
  });
});

describe('chunkAt', () => {
  it('shows each backend chunk for exactly its own window', () => {
    for (const c of chunks) {
      expect(chunkAt(chunks, (c.start + c.end) / 2)).toBe(c);
    }
  });

  it('gives a boundary instant to the chunk that starts there', () => {
    const [a, b] = chunks;
    if (a.end === b.start) expect(chunkAt(chunks, b.start)).toBe(b);
  });

  it('returns null outside every chunk', () => {
    expect(chunkAt(chunks, 0)).toBeNull();
    expect(chunkAt(chunks, 10_000)).toBeNull();
  });
});

describe('activeWordIndex', () => {
  it('highlights the same word the export highlights', () => {
    for (const c of chunks) {
      c.words.forEach((w, i) => {
        if (w.end > w.start) expect(activeWordIndex(c, (w.start + w.end) / 2)).toBe(i);
      });
    }
  });

  it('never highlights a zero-length word, like the renderer', () => {
    const chunk = {
      start: 0,
      end: 1,
      words: [
        { text: 'A', start: 0, end: 0 },
        { text: 'B', start: 0, end: 1 },
      ],
    };
    expect(activeWordIndex(chunk, 0)).toBe(1);
  });

  it('reports -1 before the chunk begins', () => {
    expect(activeWordIndex(chunks[1], chunks[0].start)).toBe(-1);
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
