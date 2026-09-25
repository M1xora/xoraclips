import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ClipCard } from './ClipCard';
import { LanguageContext } from '../../i18n/context';
import { id } from '../../i18n/id';
import type { ViralClip } from '../../lib/types';

function clip(partial: Partial<ViralClip> = {}): ViralClip {
  return {
    id: 'c1',
    title: 'Judul klip',
    start_time: 10,
    end_time: 40,
    virality_score: 90,
    key_quotes: [],
    transcript: '',
    ...partial,
  };
}

function render(c: ViralClip) {
  const noop = () => {};
  return renderToStaticMarkup(
    <LanguageContext.Provider value={{ language: 'id', setLanguage: noop, t: id }}>
      <ClipCard clip={c} index={0} marked={false} active={false} onToggleMark={noop}
        onSelect={noop} onPreview={noop} onTrim={noop} onCopy={noop} />
    </LanguageContext.Provider>,
  );
}

describe('ClipCard caption for posting (#49)', () => {
  it('shows the caption, the hashtags and the copy button', () => {
    const html = render(clip({ caption_suggestion: 'Caption dari AI', hashtag_suggestion: '#fyp #viral' }));
    expect(html).toContain(id.results.postCaption);
    expect(html).toContain('Caption dari AI');
    expect(html).toContain('#fyp #viral');
    expect(html).toContain(id.results.copyPost);
  });

  it('clamps the caption to 3 lines until it is opened', () => {
    const html = render(clip({ caption_suggestion: 'Caption dari AI' }));
    expect(html).toMatch(/<p[^>]*line-clamp-3[^>]*>Caption dari AI<\/p>/);
  });

  it('shows no block for a clip without caption or hashtags', () => {
    const html = render(clip());
    expect(html).not.toContain(id.results.postCaption);
    expect(html).not.toContain(id.results.copyPost);
  });

  it('shows only the hashtags when there is no caption', () => {
    const html = render(clip({ caption_suggestion: null, hashtag_suggestion: '#hanya' }));
    expect(html).toContain('#hanya');
    expect(html).not.toContain('line-clamp-3');
  });
});
