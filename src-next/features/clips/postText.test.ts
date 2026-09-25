import { describe, expect, it } from 'vitest';
import { postText } from './postText';

describe('postText', () => {
  it('puts the caption, a blank line, then the hashtags', () => {
    expect(
      postText({ caption_suggestion: 'Ternyata begini caranya', hashtag_suggestion: '#tips #viral' }),
    ).toBe('Ternyata begini caranya\n\n#tips #viral');
  });

  it('keeps only the part that exists', () => {
    expect(postText({ caption_suggestion: 'Hanya caption' })).toBe('Hanya caption');
    expect(postText({ hashtag_suggestion: '#hanya #hashtag' })).toBe('#hanya #hashtag');
    expect(postText({ caption_suggestion: '', hashtag_suggestion: '#a' })).toBe('#a');
  });

  it('is empty when both are missing, so the card shows nothing', () => {
    expect(postText({})).toBe('');
    expect(postText({ caption_suggestion: '  ', hashtag_suggestion: '\n' })).toBe('');
  });

  it('trims spaces and line breaks around each part', () => {
    expect(postText({ caption_suggestion: '  Caption \n', hashtag_suggestion: ' #a #b  ' })).toBe(
      'Caption\n\n#a #b',
    );
  });
});
