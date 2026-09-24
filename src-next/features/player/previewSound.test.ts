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

  it('never goes below 0 or breaks on a bad value', () => {
    expect(previewVolume(-10)).toBe(0);
    expect(previewVolume(Number.NaN)).toBe(100);
  });
});
