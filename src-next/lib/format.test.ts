import { describe, expect, it } from 'vitest';
import { formatPreciseTimecode, formatTimecode, parseTimecode } from './format';

describe('parseTimecode (#56)', () => {
  it.each([
    ['83', 83],
    ['83.5', 83.5],
    ['1:23', 83],
    ['1:23.5', 83.5],
    ['1:23,5', 83.5],
    ['01:23', 83],
    ['00:17.28', 17.28],
    ['1:01:23', 3683],
    [' 2:05 ', 125],
  ])('%s is %d seconds', (text, seconds) => {
    expect(parseTimecode(text)).toBeCloseTo(seconds, 5);
  });

  it.each(['', 'abc', '1:2:3:4', '1:75', '1:60:00', '-5', '1.2.3', '1:'])('%j is not a time', (text) => {
    expect(parseTimecode(text)).toBeNull();
  });
});

describe('formatPreciseTimecode (#56)', () => {
  it.each([
    [83, '01:23'],
    [83.5, '01:23.5'],
    [83.25, '01:23.25'],
    [17.28, '00:17.28'],
    [17.05, '00:17.05'],
    [3683, '1:01:23'],
    [0, '00:00'],
    [59.999, '01:00'],
  ])('%d is %s', (seconds, text) => {
    expect(formatPreciseTimecode(seconds)).toBe(text);
  });

  it('pads like formatTimecode, so the modal shows one time style', () => {
    expect(formatPreciseTimecode(83)).toBe(formatTimecode(83));
  });

  it('reads back to the same time', () => {
    for (const t of [0, 7.5, 17.05, 83.25, 599.99, 3683.1]) {
      expect(parseTimecode(formatPreciseTimecode(t))).toBeCloseTo(t, 2);
    }
  });
});
