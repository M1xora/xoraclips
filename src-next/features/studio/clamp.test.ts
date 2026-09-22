import { describe, expect, it } from 'vitest';
import { formatTitleSmart, getCenterBounds, getMaxPositions } from './derive';
import type { AspectRatioOption } from '../../lib/types';

/**
 * The ceiling on a position is not fixed: it depends on how many lines the
 * title wraps to, and that depends on the font size. A value set under one
 * ceiling can end up above the next one.
 *
 * The backend clamps before rendering (video_engine.py:774), so the export
 * was always right. The preview did not, so it drew the title where the
 * export would not put it. App.tsx now derives clamped values for both.
 */

const RATIOS: AspectRatioOption[] = ['9:16', '1:1', '4:3', '16:9'];

/** What App.tsx computes, kept here so the rule itself is tested. */
function clamp(ratio: AspectRatioOption, lines: number, titleY: number, subY: number, subC: number) {
  const m = getMaxPositions(ratio, lines);
  const c = getCenterBounds(ratio);
  return {
    titleY: Math.min(titleY, m.maxTitleY),
    subtitleY: Math.min(subY, m.maxSubY),
    subtitleCenterY: Math.min(Math.max(subC, c.min), c.max),
  };
}

describe('the ceiling actually moves', () => {
  it('drops when a bigger font wraps the title onto another line', () => {
    // This is the case that made the preview and the render disagree.
    const title = 'Rahasia Sukses Konten Viral';
    const medium = formatTitleSmart(title, 'uppercase', 'medium');
    const big = formatTitleSmart(title, 'uppercase', 'big');

    expect(big.lineCount).toBeGreaterThan(medium.lineCount);
    expect(getMaxPositions('1:1', big.lineCount).maxTitleY).toBeLessThan(
      getMaxPositions('1:1', medium.lineCount).maxTitleY,
    );
  });

  it('never rises as lines are added', () => {
    for (const r of RATIOS) {
      let prev = Number.POSITIVE_INFINITY;
      for (const lines of [1, 2, 3, 4]) {
        const max = getMaxPositions(r, lines).maxTitleY;
        expect(max, `${r} at ${lines} lines`).toBeLessThanOrEqual(prev);
        prev = max;
      }
    }
  });
});

describe('clamping', () => {
  it('pulls a stale title position down to the new ceiling', () => {
    // 15 was legal at 2 lines; at 3 it is not.
    const before = getMaxPositions('1:1', 2).maxTitleY;
    const after = getMaxPositions('1:1', 3).maxTitleY;
    expect(clamp('1:1', 3, before, 0, 50).titleY).toBe(after);
  });

  it('leaves a value that is already legal alone', () => {
    const max = getMaxPositions('9:16', 2).maxTitleY;
    expect(clamp('9:16', 2, max - 5, 0, 50).titleY).toBe(max - 5);
  });

  it('never returns a title position above the ceiling, for any combination', () => {
    for (const r of RATIOS) {
      for (const lines of [1, 2, 3, 4]) {
        for (const raw of [0, 10, 25, 45, 100]) {
          const out = clamp(r, lines, raw, 0, 50).titleY;
          expect(out, `${r} ${lines}L raw=${raw}`).toBeLessThanOrEqual(
            getMaxPositions(r, lines).maxTitleY,
          );
        }
      }
    }
  });

  it('clamps the bottom subtitle the same way', () => {
    for (const r of RATIOS) {
      const max = getMaxPositions(r, 1).maxSubY;
      expect(clamp(r, 1, 0, max + 20, 50).subtitleY).toBe(max);
    }
  });

  it('holds the centred subtitle inside both bounds', () => {
    for (const r of RATIOS) {
      const c = getCenterBounds(r);
      expect(clamp(r, 1, 0, 0, -50).subtitleCenterY).toBe(c.min);
      expect(clamp(r, 1, 0, 0, 500).subtitleCenterY).toBe(c.max);
      const mid = (c.min + c.max) / 2;
      expect(clamp(r, 1, 0, 0, mid).subtitleCenterY).toBe(mid);
    }
  });

  it('is idempotent, so clamping twice changes nothing', () => {
    const once = clamp('4:3', 3, 99, 99, 99);
    const twice = clamp('4:3', 3, once.titleY, once.subtitleY, once.subtitleCenterY);
    expect(twice).toEqual(once);
  });
});
