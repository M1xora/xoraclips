import type { CaptionStyle, TextCaseOption, TranscriptLine } from '../../lib/types';
import { applyLetterCase } from './derive';

/**
 * Caption styling and word timing for the preview.
 *
 * Colours come from ClipStudioSection.tsx:3013-3053, where each style
 * highlighted one word in an accent colour against white. The old preview
 * showed a fixed sample phrase per style; this uses the clip's own words, so
 * what the user reads is what the render will burn in.
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

export interface CaptionChunk {
  words: CaptionWord[];
  start: number;
  end: number;
}

/** Words shown at once. The renderer groups captions the same way. */
const WORDS_PER_CHUNK = 3;

/**
 * Splits a transcript line into evenly timed words.
 *
 * The backend produces real per-word timings with Whisper. The frontend has
 * only line-level timings, so words are spread across the line. The result
 * is close enough to judge style and placement, and it is labelled as a
 * preview rather than presented as frame-accurate.
 */
function wordsFromLine(line: TranscriptLine): CaptionWord[] {
  const words = line.text.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return [];

  const span = Math.max(0.1, line.end - line.start);
  const per = span / words.length;

  return words.map((text, i) => ({
    text,
    start: line.start + i * per,
    end: line.start + (i + 1) * per,
  }));
}

/**
 * Builds the caption chunks covering one clip.
 *
 * Falls back to the clip's own transcript string when no timed lines exist,
 * which is common for videos without subtitles.
 */
export function buildCaptionChunks(
  transcript: TranscriptLine[] | undefined,
  clipStart: number,
  clipEnd: number,
  fallbackText?: string,
): CaptionChunk[] {
  const lines = (transcript ?? []).filter(
    (l) => l.end > clipStart && l.start < clipEnd,
  );

  let words: CaptionWord[] = [];

  if (lines.length > 0) {
    words = lines.flatMap(wordsFromLine);
  } else if (fallbackText?.trim()) {
    // No timings: spread the clip's transcript evenly across its duration.
    const all = fallbackText.trim().split(/\s+/).filter(Boolean);
    const span = Math.max(0.1, clipEnd - clipStart);
    const per = span / Math.max(1, all.length);
    words = all.map((text, i) => ({
      text,
      start: clipStart + i * per,
      end: clipStart + (i + 1) * per,
    }));
  }

  // Keep only what falls inside the clip.
  words = words.filter((w) => w.end > clipStart && w.start < clipEnd);
  if (words.length === 0) return [];

  const chunks: CaptionChunk[] = [];
  for (let i = 0; i < words.length; i += WORDS_PER_CHUNK) {
    const group = words.slice(i, i + WORDS_PER_CHUNK);
    chunks.push({
      words: group,
      start: group[0].start,
      end: group[group.length - 1].end,
    });
  }
  return chunks;
}

/** The chunk covering `time`, or null between chunks. */
export function chunkAt(chunks: CaptionChunk[], time: number): CaptionChunk | null {
  return chunks.find((c) => time >= c.start && time <= c.end) ?? null;
}

/**
 * Which word inside the chunk is currently spoken.
 * Returns -1 before the first word starts.
 */
export function activeWordIndex(chunk: CaptionChunk, time: number): number {
  return chunk.words.findIndex((w) => time >= w.start && time <= w.end);
}

/** Applies the case option to a word for display. */
export function renderWord(word: string, textCase: TextCaseOption): string {
  return applyLetterCase(word, textCase);
}
