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

function render(c: ViralClip, clipRange?: [number, number] | null, clipPreset?: string) {
  const noop = () => {};
  return renderToStaticMarkup(
    <LanguageContext.Provider value={{ language: 'id', setLanguage: noop, t: id }}>
      <ClipCard clip={c} clipRange={clipRange} clipPreset={clipPreset} index={0} marked={false}
        active={false} onToggleMark={noop} onSelect={noop} onPreview={noop} onTrim={noop}
        onCopy={noop} />
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


describe('ClipCard length against the preset range (#94)', () => {
  const THIRTY: [number, number] = [20, 40];

  it('marks a clip that runs over, with the difference', () => {
    const html = render(clip({ start_time: 100, end_time: 149.1 }), THIRTY, '30s');
    expect(html).toContain(id.results.lengthOver(9, '30s', 20, 40));
    expect(html).toContain(id.results.lengthOutsideHint);
  });

  it('marks a clip that falls under', () => {
    const html = render(clip({ start_time: 100, end_time: 115 }), THIRTY, '30s');
    expect(html).toContain(id.results.lengthUnder(5, '30s', 20, 40));
  });

  it('says nothing about a clip inside the range', () => {
    const html = render(clip({ start_time: 100, end_time: 130 }), THIRTY, '30s');
    expect(html).not.toContain(id.results.lengthOutsideHint);
  });

  it('says nothing without a range (an analysis from before #94)', () => {
    const html = render(clip({ start_time: 100, end_time: 149.1 }));
    expect(html).not.toContain(id.results.lengthOutsideHint);
  });

  it('never claims a difference of zero seconds', () => {
    // 40.4s is over the 20-40s preset, but rounds to "0s over".
    const html = render(clip({ start_time: 100, end_time: 140.4 }), THIRTY, '30s');
    expect(html).toContain(id.results.lengthOver(1, '30s', 20, 40));
    expect(html).not.toContain(id.results.lengthOver(0, '30s', 20, 40));
  });
});
