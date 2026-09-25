import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { TrimmerModal } from './TrimmerModal';
import { LanguageContext } from '../../i18n/context';
import { id } from '../../i18n/id';
import type { TranscriptLine, ViralClip } from '../../lib/types';

const clip: ViralClip = {
  id: 'c1', title: 'Klip', start_time: 17.28, end_time: 30, virality_score: 90, key_quotes: [], transcript: '',
};

function render(transcript?: TranscriptLine[]) {
  return renderToStaticMarkup(
    <LanguageContext.Provider value={{ language: 'id', setLanguage: () => {}, t: id }}>
      <TrimmerModal open clip={clip} videoId="qedBB492cQY" videoDuration={600}
        transcript={transcript} onApply={() => {}} onClose={() => {}} />
    </LanguageContext.Provider>,
  );
}

describe('TrimmerModal (#56)', () => {
  it('shows the typed start and end with hundredths', () => {
    const html = render();
    expect(html).toContain('value="0:17.28"');
    expect(html).toContain('value="0:30"');
  });

  it('lists transcript lines with start/end buttons and marks those inside the clip', () => {
    const html = render([
      { start: 15.08, end: 19.24, text: 'yang namanya sehat itu susah kalau sakit' },
      { start: 17.28, end: 21.72, text: 'mah gampang gitu kita tinggal keluar' },
      { start: 1000, end: 1004, text: 'jauh di luar jendela timeline' },
    ]);
    expect(html).toContain(id.trimmer.linesTitle);
    expect(html).toContain('mah gampang gitu kita tinggal keluar');
    expect(html).not.toContain('jauh di luar jendela timeline');
    expect(html.match(new RegExp(id.trimmer.setStart, 'g'))).toHaveLength(2);
    // The line before the clip is not marked; the one starting at the clip start is.
    expect(html).toMatch(/<li data-inside="true"[^>]*>(?:(?!<\/li>).)*mah gampang/);
    expect(html).not.toMatch(/<li data-inside="true"[^>]*>(?:(?!<\/li>).)*yang namanya/);
  });

  it('shows no line list without a transcript', () => {
    expect(render()).not.toContain(id.trimmer.linesTitle);
    expect(render([])).not.toContain(id.trimmer.linesTitle);
  });
});
