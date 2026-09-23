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
  // Not trimmed: a space inside a word span is exactly the #17 bug.
  const words = [...html.matchAll(/<span([^>]*)>([^<]*)<\/span>/g)]
    .filter((m) => !m[1].includes('class='))
    .map((m) => ({ text: decode(m[2]), active: m[1].includes('data-active="true"') }));
  // The overlay holds nothing but the caption, so its text is what shows.
  const shown = decode(html.replace(/<[^>]+>/g, ''));
  return { html, words, shown };
}

function decode(text: string) {
  return text
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, '&');
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

  it('puts the spaces between words, never inside a word (#17)', () => {
    for (const api of apiChunks) {
      const { words, shown } = render(ted.clip_start + (api.start + api.end) / 2);
      expect(shown).toBe(api.text);
      for (const { text } of words) expect(text).toBe(text.trim());
    }
  });

  it('marks the spoken word by colour only, as the export does (#17)', () => {
    // A scaled word grew over the spaces beside it and looked glued on.
    const { html } = render(ted.clip_start + (apiChunks[0].start + apiChunks[0].end) / 2);
    expect(html).toContain('data-active="true"');
    expect(html).not.toMatch(/scale\(/);
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
