import { describe, expect, it } from 'vitest';
import {
  buildJson,
  buildMarkdown,
  buildSrt,
  clipTitle,
  formatTimestamps,
  safeFileName,
  srtTimestamp,
  timestamp,
} from './exporters';
import type { AnalyzeResponse, TranscriptLine, ViralClip } from '../../lib/types';

function clip(over: Partial<ViralClip> = {}): ViralClip {
  return {
    id: 'a',
    title: 'Judul',
    start_time: 10,
    end_time: 30,
    virality_score: 8,
    key_quotes: [],
    transcript: '',
    ...over,
  };
}

describe('timestamp', () => {
  it('pads to mm:ss under an hour', () => {
    expect(timestamp(0)).toBe('00:00');
    expect(timestamp(83)).toBe('01:23');
    expect(timestamp(3599)).toBe('59:59');
  });

  it('adds hours past one', () => {
    expect(timestamp(3600)).toBe('1:00:00');
    expect(timestamp(3723)).toBe('1:02:03');
  });

  it('floors fractions and refuses negatives', () => {
    expect(timestamp(83.9)).toBe('01:23');
    expect(timestamp(-5)).toBe('00:00');
  });
});

describe('srtTimestamp', () => {
  it('uses the comma form SRT requires', () => {
    expect(srtTimestamp(0)).toBe('00:00:00,000');
    expect(srtTimestamp(83.456)).toBe('00:01:23,456');
    expect(srtTimestamp(3723.1)).toBe('01:02:03,100');
  });

  it('always pads milliseconds to three digits', () => {
    // A player would reject a two-digit fraction.
    expect(srtTimestamp(1.05)).toBe('00:00:01,050');
    expect(srtTimestamp(1.005)).toBe('00:00:01,005');
  });
});

describe('formatTimestamps', () => {
  const clips = [
    clip({ id: 'b', start_time: 100, end_time: 120, title_suggestion: 'Kedua' }),
    clip({ id: 'a', start_time: 10, end_time: 30, title_suggestion: 'Pertama' }),
  ];

  it('sorts by start time whatever order it is given', () => {
    expect(formatTimestamps(clips, 'plain')).toBe('00:10 - 00:30\n01:40 - 02:00');
  });

  it('adds titles when asked', () => {
    expect(formatTimestamps(clips, 'titled')).toBe(
      '00:10 - 00:30 | Pertama\n01:40 - 02:00 | Kedua',
    );
  });

  it('prepends an intro chapter, which YouTube requires to start at zero', () => {
    const out = formatTimestamps(clips, 'chapters');
    expect(out.split('\n')[0]).toBe('00:00 Intro');
    expect(out).toContain('00:10 Pertama');
  });

  it('does not prepend one when a clip already starts at zero', () => {
    const out = formatTimestamps([clip({ start_time: 0, title_suggestion: 'Awal' })], 'chapters');
    expect(out).toBe('00:00 Awal');
  });

  it('handles an empty list', () => {
    expect(formatTimestamps([], 'plain')).toBe('');
    expect(formatTimestamps([], 'chapters')).toBe('00:00 Intro');
  });
});

describe('clipTitle', () => {
  it('prefers a rename over the AI suggestion', () => {
    expect(clipTitle(clip({ custom_title: 'Punya Saya', title_suggestion: 'AI' }))).toBe(
      'Punya Saya',
    );
  });

  it('falls back through suggestion then title', () => {
    expect(clipTitle(clip({ title_suggestion: 'AI' }))).toBe('AI');
    expect(clipTitle(clip({ title: 'Dasar' }))).toBe('Dasar');
  });

  it('ignores a blank rename', () => {
    expect(clipTitle(clip({ custom_title: '   ', title_suggestion: 'AI' }))).toBe('AI');
  });
});

describe('buildSrt', () => {
  const lines: TranscriptLine[] = [
    { start: 0, end: 5, text: 'sebelum' },
    { start: 12, end: 15, text: 'di dalam' },
    { start: 20, end: 24, text: 'juga di dalam' },
    { start: 100, end: 105, text: 'sesudah' },
  ];

  it('keeps only what overlaps the clip', () => {
    const out = buildSrt(lines, clip({ start_time: 10, end_time: 30 }));
    expect(out).toContain('di dalam');
    expect(out).not.toContain('sebelum');
    expect(out).not.toContain('sesudah');
  });

  it('rebases times so the clip starts at zero', () => {
    // A line at 12s in a clip starting at 10s becomes 2s.
    const out = buildSrt(lines, clip({ start_time: 10, end_time: 30 }));
    expect(out).toContain('00:00:02,000 --> 00:00:05,000');
  });

  it('numbers entries from one, in order', () => {
    const out = buildSrt(lines, clip({ start_time: 10, end_time: 30 }));
    expect(out.startsWith('1\n')).toBe(true);
    expect(out).toContain('\n2\n');
  });

  it('trims a line that straddles the clip edge', () => {
    const straddle: TranscriptLine[] = [{ start: 5, end: 15, text: 'melintas' }];
    const out = buildSrt(straddle, clip({ start_time: 10, end_time: 30 }));
    // Clamped to the clip start, so it begins at zero, not minus five.
    expect(out).toContain('00:00:00,000 --> 00:00:05,000');
  });

  it('drops blank lines', () => {
    const blank: TranscriptLine[] = [{ start: 12, end: 14, text: '   ' }];
    expect(buildSrt(blank, clip())).toBe('');
  });

  it('exports the whole transcript when no clip is given', () => {
    const out = buildSrt(lines);
    expect(out).toContain('sebelum');
    expect(out).toContain('sesudah');
  });

  it('returns empty for an empty transcript', () => {
    expect(buildSrt([], clip())).toBe('');
  });
});

function response(over: Partial<AnalyzeResponse> = {}): AnalyzeResponse {
  return {
    video_id: 'abc',
    title: 'Video Uji',
    duration: 600,
    heatmap: [],
    summary: '',
    clips: [clip({ title_suggestion: 'Klip Satu' })],
    ...over,
  };
}

describe('buildJson', () => {
  it('produces valid JSON', () => {
    expect(() => JSON.parse(buildJson(response()))).not.toThrow();
  });

  it('carries the clip count and computed duration', () => {
    const j = JSON.parse(buildJson(response()));
    expect(j.clip_count).toBe(1);
    expect(j.clips[0].duration).toBe(20);
    expect(j.clips[0].title).toBe('Klip Satu');
  });

  it('sorts clips by start time', () => {
    const j = JSON.parse(
      buildJson(
        response({
          clips: [clip({ id: 'b', start_time: 100 }), clip({ id: 'a', start_time: 5 })],
        }),
      ),
    );
    expect(j.clips[0].start_time).toBeLessThan(j.clips[1].start_time);
  });
});

describe('buildMarkdown', () => {
  it('starts with the video title as a heading', () => {
    expect(buildMarkdown(response()).startsWith('# Video Uji')).toBe(true);
  });

  it('falls back to the id when there is no title', () => {
    expect(buildMarkdown(response({ title: '' }))).toContain('# abc');
  });

  it('includes quotes as a blockquote', () => {
    const md = buildMarkdown(response({ clips: [clip({ key_quotes: ['satu', 'dua'] })] }));
    expect(md).toContain('> satu');
    expect(md).toContain('> dua');
  });

  it('leaves out empty optional fields', () => {
    const md = buildMarkdown(response());
    expect(md).not.toContain('- Caption:');
    expect(md).not.toContain('- Hashtags:');
  });

  it('ends with exactly one newline', () => {
    const md = buildMarkdown(response());
    expect(md.endsWith('\n')).toBe(true);
    expect(md.endsWith('\n\n')).toBe(false);
  });
});

describe('safeFileName', () => {
  it('strips what Windows rejects, like the backend does', () => {
    expect(safeFileName('a/b:c*d?e"f<g>h|i')).toBe('abcdefghi');
  });

  it('strips the backslash too, as the backend rule does', () => {
    expect(safeFileName('Q&A \\ Part 2')).toBe('Q&A  Part 2');
  });

  it('falls back when nothing is left', () => {
    expect(safeFileName('///')).toBe('export');
    expect(safeFileName('   ', 'klip')).toBe('klip');
  });
});
