import { describe, expect, it } from 'vitest';
import { downloadNoteText } from './downloadNote';
import { id } from '../../i18n/id';
import { en } from '../../i18n/en';

describe('download status line (#10)', () => {
  it('says YouTube only sent audio and that it is trying again', () => {
    const text = downloadNoteText({ code: 'audio_only_retry', method: 1, methods: 3 }, id);
    expect(text).toBe('YouTube hanya mengirim audio. Mencoba lagi (cara 1 dari 3)...');
  });

  it('says which download method it moved on to', () => {
    expect(downloadNoteText({ code: 'next_method', method: 2, methods: 3 }, en)).toBe(
      'Trying download method 2 of 3...',
    );
  });

  it('shows nothing without a note, or for a code it does not know', () => {
    expect(downloadNoteText(undefined, id)).toBeNull();
    expect(downloadNoteText({ code: 'something_new', method: 1, methods: 3 }, id)).toBeNull();
  });
});
