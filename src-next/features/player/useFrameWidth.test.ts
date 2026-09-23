import { describe, expect, it } from 'vitest';
import { frameWidthFor, MAX_FRAME_W } from './useFrameWidth';

describe('preview frame width (#20)', () => {
  it('is 15% larger than the old 288px frame', () => {
    expect(MAX_FRAME_W).toBe(Math.round(288 * 1.15));
  });

  it('uses the full size when the column has room', () => {
    expect(frameWidthFor(368)).toBe(MAX_FRAME_W);
  });

  it('shrinks to the column on a phone instead of overflowing', () => {
    // 360px phone: 16px page gutter, 1px panel border and 16px panel
    // padding on each side.
    expect(frameWidthFor(360 - 2 * (16 + 1 + 16))).toBe(294);
    expect(frameWidthFor(295.6)).toBe(295);
  });

  it('keeps the full size before the column is measured', () => {
    expect(frameWidthFor(0)).toBe(MAX_FRAME_W);
  });
});
