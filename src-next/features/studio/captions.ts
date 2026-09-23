import type { CaptionStyle } from '../../lib/types';
import type { ApiCaptionChunk } from '../../api/client';

/**
 * Caption styling and timing helpers for the preview.
 *
 * The words, the chunking and each word's highlight timing are NOT decided
 * here. They come from the backend (`POST /api/caption-chunks`, backend
 * captions.py), the same code that writes the export's .ass file, so the
 * preview shows exactly what the render burns in. Word timings are spread
 * evenly across each YouTube caption line on both sides; neither side uses
 * Whisper while a transcript exists.
 *
 * Colours come from ClipStudioSection.tsx:3013-3053, where each style
 * highlighted one word in an accent colour against white.
 */

export interface CaptionTheme {
  /** Colour of the emphasised word. */
  accent: string;
  base: string;
  /** Extra text-shadow layers, for the styles that glowed. */
  glow?: string;
}

export const CAPTION_THEMES: Record<Exclude<CaptionStyle, 'none'>, CaptionTheme> = {
  viral_pop: { accent: '#FFE600', base: '#FFFFFF' },
  beast_punch: { accent: '#00FF66', base: '#FFFFFF' },
  cyber_violet: { accent: '#D946EF', base: '#FFFFFF', glow: '0 0 12px rgba(217,70,239,.55)' },
  fire_red: { accent: '#FF2E2E', base: '#FFFFFF', glow: '0 0 12px rgba(255,46,46,.5)' },
  electric_cyan: { accent: '#00F0FF', base: '#FFFFFF', glow: '0 0 12px rgba(0,240,255,.55)' },
  golden_aura: { accent: '#FFB800', base: '#FFFFFF', glow: '0 0 14px rgba(255,184,0,.5)' },
  clean_minimal: { accent: '#FFFFFF', base: '#FFFFFF' },
};

/** Readable labels for the style picker. */
export const CAPTION_STYLE_LABELS: Record<CaptionStyle, string> = {
  viral_pop: 'Viral Pop',
  beast_punch: 'Beast Punch',
  cyber_violet: 'Cyber Violet',
  fire_red: 'Fire Red',
  electric_cyan: 'Electric Cyan',
  golden_aura: 'Golden Aura',
  clean_minimal: 'Clean Minimal',
  none: 'None',
};


export interface CaptionWord {
  text: string;
  start: number;
  end: number;
}

/** A caption chunk in absolute source-video time. */
export interface CaptionChunk {
  words: CaptionWord[];
  start: number;
  end: number;
}

/**
 * Moves backend chunks (relative to the clip start, like the .ass file) onto
 * the source video's timeline, which is what the preview player reports.
 */
export function chunksFromApi(chunks: ApiCaptionChunk[], clipStart: number): CaptionChunk[] {
  return chunks.map((c) => ({
    start: clipStart + c.start,
    end: clipStart + c.end,
    words: c.words.map((w) => ({
      text: w.text,
      start: clipStart + w.start,
      end: clipStart + w.end,
    })),
  }));
}

/**
 * The chunk on screen at `time`, or null between chunks. Intervals are
 * half-open [start, end), as ASS events are, so a boundary instant belongs
 * to the chunk that starts there.
 */
export function chunkAt(chunks: CaptionChunk[], time: number): CaptionChunk | null {
  return chunks.find((c) => time >= c.start && time < c.end) ?? null;
}

/**
 * Which word inside the chunk is highlighted. Zero-length words are never
 * highlighted, matching the renderer, which skips them. Returns -1 when no
 * word is active.
 */
export function activeWordIndex(chunk: CaptionChunk, time: number): number {
  return chunk.words.findIndex((w) => w.end > w.start && time >= w.start && time < w.end);
}
