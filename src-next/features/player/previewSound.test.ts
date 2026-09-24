import { describe, expect, it } from 'vitest';
import { boostedBeyondPreview, previewVolume } from './previewSound';

describe('previewVolume (#40)', () => {
  it('follows the original audio volume', () => {
    expect(previewVolume(100)).toBe(100);
    expect(previewVolume(45)).toBe(45);
    expect(previewVolume(0)).toBe(0);
  });

  it('stops at 100, the YouTube player maximum', () => {
    expect(previewVolume(150)).toBe(100);
    expect(boostedBeyondPreview(150)).toBe(true);
    expect(boostedBeyondPreview(100)).toBe(false);
  });

  it('also notes a hook sound above 100%', () => {
    expect(boostedBeyondPreview(100, 180)).toBe(true);
  });

  it('reads bad values the same way in both helpers', () => {
    expect(previewVolume(-10)).toBe(0);
    expect(previewVolume(Number.NaN)).toBe(100);
    expect(boostedBeyondPreview(Number.NaN)).toBe(false);
    expect(previewVolume(Number.POSITIVE_INFINITY)).toBe(100);
    expect(boostedBeyondPreview(Number.POSITIVE_INFINITY)).toBe(false);
  });
});
