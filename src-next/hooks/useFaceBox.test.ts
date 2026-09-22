import { describe, expect, it } from 'vitest';
import { faceOffsetPercent } from './useFaceBox';
import type { FaceBox } from '../api/client';

function box(cx: number, found = true): FaceBox {
  return { found, cx, cy: 0.4, w: 0.2, h: 0.25, frame_url: '' };
}

// A 9:16 preview frame against the 16:9 source that covers it.
const FRAME_W = 288;
const SOURCE_W = 910;

describe('faceOffsetPercent', () => {
  it('does not move a centred face', () => {
    expect(faceOffsetPercent(box(0.5), FRAME_W, SOURCE_W)).toBeCloseTo(0, 5);
  });

  it('shifts right when the speaker sits left of centre', () => {
    // Moving the source right brings a left-hand face into view.
    expect(faceOffsetPercent(box(0.3), FRAME_W, SOURCE_W)).toBeGreaterThan(0);
  });

  it('shifts left when the speaker sits right of centre', () => {
    expect(faceOffsetPercent(box(0.7), FRAME_W, SOURCE_W)).toBeLessThan(0);
  });

  it('never exposes empty space at the edge', () => {
    const maxPct = ((SOURCE_W - FRAME_W) / 2 / SOURCE_W) * 100;
    for (const cx of [0, 0.05, 0.95, 1]) {
      expect(Math.abs(faceOffsetPercent(box(cx), FRAME_W, SOURCE_W))).toBeLessThanOrEqual(
        maxPct + 1e-9,
      );
    }
  });

  it('returns nothing to apply when no box is given', () => {
    expect(faceOffsetPercent(null, FRAME_W, SOURCE_W)).toBe(0);
  });

  it('ignores a box the detector marked as not found', () => {
    expect(faceOffsetPercent(box(0.2, false), FRAME_W, SOURCE_W)).toBe(0);
  });

  it('stays still when the source is no wider than the frame', () => {
    // 16:9 preview: there is nothing to slide.
    expect(faceOffsetPercent(box(0.2), 288, 288)).toBe(0);
  });

  it('moves further for a face further off centre', () => {
    const near = Math.abs(faceOffsetPercent(box(0.45), FRAME_W, SOURCE_W));
    const far = Math.abs(faceOffsetPercent(box(0.2), FRAME_W, SOURCE_W));
    expect(far).toBeGreaterThan(near);
  });

  it('is symmetric about the centre', () => {
    const left = faceOffsetPercent(box(0.35), FRAME_W, SOURCE_W);
    const right = faceOffsetPercent(box(0.65), FRAME_W, SOURCE_W);
    expect(left).toBeCloseTo(-right, 5);
  });

  it('brings an off-centre face inside the visible window', () => {
    // The real goal: after the shift, the face must be within the frame.
    const cx = 0.3;
    const offsetPct = faceOffsetPercent(box(cx), FRAME_W, SOURCE_W);
    const facePx = cx * SOURCE_W + (offsetPct / 100) * SOURCE_W;
    const visibleLeft = (SOURCE_W - FRAME_W) / 2;
    const visibleRight = visibleLeft + FRAME_W;

    expect(facePx).toBeGreaterThanOrEqual(visibleLeft);
    expect(facePx).toBeLessThanOrEqual(visibleRight);
  });
});
