import { describe, expect, it } from 'vitest';
import { titleChoices } from './titleChoices';

const OPTIONS = [
  'dr. Tirta: Olahraga Berat Bisa Rusak Jantung?',
  'Ternyata Lari Tiap Hari Nggak Selalu Sehat',
  'Host Nggak Nyangka Jawaban Tamunya Begini',
];

describe('title choices (#31)', () => {
  it('the first option is active by default and picking it clears the custom title', () => {
    const choices = titleChoices(OPTIONS, '');
    expect(choices.map((c) => c.active)).toEqual([true, false, false]);
    expect(choices[0].value).toBe('');
  });

  it('picking option 2 or 3 stores it as the custom title, and marks it active', () => {
    const choices = titleChoices(OPTIONS, '');
    expect(choices[1].value).toBe(OPTIONS[1]);
    expect(titleChoices(OPTIONS, OPTIONS[2]).map((c) => c.active)).toEqual([false, false, true]);
  });

  it('a title typed by hand leaves no option marked', () => {
    expect(titleChoices(OPTIONS, 'Judul Buatan Sendiri').some((c) => c.active)).toBe(false);
  });

  it('shows nothing for analyses made before #31 or with a single option', () => {
    expect(titleChoices(undefined, '')).toEqual([]);
    expect(titleChoices([OPTIONS[0]], '')).toEqual([]);
    expect(titleChoices(['  ', ''], '')).toEqual([]);
  });
});
