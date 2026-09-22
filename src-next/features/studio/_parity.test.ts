import { describe, expect, it } from 'vitest';
import { formatTitleSmart } from './derive';
import type { FontSizeOption, TextCaseOption } from '../../lib/types';

// Verbatim copy of the old implementation, for comparison only.
function applyOld(text: string, style: TextCaseOption): string {
  if (style === 'uppercase') return text.toUpperCase();
  if (style === 'lowercase') return text.toLowerCase();
  return text.toLowerCase().replace(/(?:^|\s|\b)\w/g, (c) => c.toUpperCase());
}
function oldFormat(rawText: string, style: TextCaseOption, sizePreset: FontSizeOption) {
  const raw = rawText.trim();
  if (!raw) return { formatted: '', lineCount: 1 };
  const cased = applyOld(raw, style);
  if (cased.includes('\n')) {
    const manualLines = cased.split('\n').map((l) => l.trim()).filter(Boolean);
    return { formatted: manualLines.join('\n'), lineCount: Math.max(1, manualLines.length) };
  }
  const words = cased.split(/\s+/).filter(Boolean);
  const maxSingleLen = sizePreset === 'small' ? 24 : sizePreset === 'big' ? 13 : 19;
  if (words.length <= 1 || cased.length <= maxSingleLen) return { formatted: cased, lineCount: 1 };
  const totalLen = cased.length;
  const targetLines = Math.min(4, Math.max(2, Math.ceil(totalLen / maxSingleLen)));
  const targetPerLine = totalLen / targetLines;
  const lines: string[] = [];
  let currentLine: string[] = [];
  let currentLen = 0;
  for (let i = 0; i < words.length; i++) {
    const w = words[i];
    const remainingWords = words.length - i;
    const remainingLines = targetLines - lines.length;
    if (remainingLines > 1 && currentLine.length > 0 &&
        (currentLen + w.length > targetPerLine * 1.15 || remainingWords <= remainingLines - 1)) {
      lines.push(currentLine.join(' ')); currentLine = [w]; currentLen = w.length;
    } else { currentLine.push(w); currentLen += w.length + 1; }
  }
  if (currentLine.length > 0) lines.push(currentLine.join(' '));
  return { formatted: lines.join('\n'), lineCount: Math.max(1, lines.length) };
}

const TITLES = [
  '', 'Short', 'Growth hacking tips!',
  'This is a reasonably long clip title for testing',
  'the quick brown fox jumps over the lazy dog again and again',
  'Why Most Startups Fail Within The First Eighteen Months Of Operation',
  'manual\nbreaks\nhere', 'one\n\n\ntwo', 'supercalifragilisticexpialidocious',
  'A B C D E F G H I J K L M N O P', 'Emoji title 🚀 with symbols & more',
  '   padded   spaces   ', 'word '.repeat(60).trim(),
];
const CASES: TextCaseOption[] = ['uppercase', 'lowercase', 'capitalize'];
const SIZES: FontSizeOption[] = ['small', 'medium', 'big'];

describe('formatTitleSmart parity with the original', () => {
  it('matches on every title, case and size combination', () => {
    let checked = 0;
    for (const title of TITLES) {
      for (const c of CASES) {
        for (const s of SIZES) {
          expect(formatTitleSmart(title, c, s), `${JSON.stringify(title)} / ${c} / ${s}`)
            .toEqual(oldFormat(title, c, s));
          checked++;
        }
      }
    }
    expect(checked).toBe(TITLES.length * CASES.length * SIZES.length);
  });
});
