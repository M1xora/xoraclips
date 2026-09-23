import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { CaptionOverlay } from './CaptionOverlay';
import { chunksFromApi } from './captions';
import type { ApiCaptionChunk } from '../../api/client';
import ted from './__fixtures__/caption-chunks.ted.json';

const apiChunks = ted.chunks as ApiCaptionChunk[];
const chunks = chunksFromApi(apiChunks, ted.clip_start);

function render(time: number) {
  const html = renderToStaticMarkup(
    <CaptionOverlay
      chunks={chunks}
      currentTime={time}
      style="viral_pop"
      font="Outfit"
      fontSize="medium"
      positionMode="bottom"
      bottomPercent={18}
      centerPercent={50}
    />,
  );
  // Word spans are the innermost spans; the wrapper span has a class.
  const words = [...html.matchAll(/<span([^>]*)>([^<]*)<\/span>/g)]
    .filter((m) => !m[1].includes('class='))
    .map((m) => ({ text: m[2].trim(), active: m[1].includes('data-active="true"') }));
  return { html, words };
}

describe('CaptionOverlay', () => {
  it('shows exactly the backend chunk text at every word', () => {
    for (const api of apiChunks) {
      for (const w of api.words) {
        if (w.end <= w.start) continue;
        const { words } = render(ted.clip_start + (w.start + w.end) / 2);
        expect(words.map((x) => x.text).join(' ')).toBe(api.text);
      }
    }
  });

  it('puts a visible space between words, outside the word boxes (#17)', () => {
    for (const api of apiChunks) {
      if (api.words.length < 2) continue;
      const { html } = render(ted.clip_start + (api.start + api.end) / 2);
      // A trailing space inside an inline-block word box is dropped by the
      // browser, so no word box may end with one.
      expect(html).not.toMatch(/ <\/span>/);
      // What the browser lays out, tags removed, reads as the chunk text.
      const shown = html
        .match(/<span class="inline-block[^>]*>(.*)<\/span><\/div>$/)?.[1]
        .replace(/<[^>]+>/g, '');
      expect(shown).toBe(api.text);
    }
  });

  it('highlights the word the export highlights', () => {
    for (const api of apiChunks) {
      api.words.forEach((w, i) => {
        if (w.end <= w.start) return;
        const { words } = render(ted.clip_start + (w.start + w.end) / 2);
        expect(words.findIndex((x) => x.active)).toBe(i);
      });
    }
  });

  it('shows no punctuation from the source captions', () => {
    // The source line was "Beberapa tahun lalu, saya mendobrak masuk rumah sendiri."
    for (const api of apiChunks) {
      const { words } = render(ted.clip_start + (api.start + api.end) / 2);
      for (const { text } of words) {
        // Letters/digits, a hyphen inside a word, and marks that belong to a
        // number (3,5 10:30 24/7 50% $5 -5), the same rule as the backend.
        expect(text).toMatch(
          /^(?:[$€£¥-](?=\d))?(?:[\p{L}\p{N}\p{M}]|(?<=[\p{L}\p{N}])-(?=[\p{L}\p{N}])|(?<=\d)[.,:/](?=\d)|(?<=\d)%)+$/u,
        );
      }
    }
  });

  it('renders nothing between chunks or with captions off', () => {
    expect(render(0).html).toBe('');
    const off = renderToStaticMarkup(
      <CaptionOverlay
        chunks={chunks}
        currentTime={chunks[0].start}
        style="none"
        font="Outfit"
        fontSize="medium"
        positionMode="bottom"
        bottomPercent={18}
        centerPercent={50}
      />,
    );
    expect(off).toBe('');
  });
});
