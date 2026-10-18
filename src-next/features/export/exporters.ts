import type { AnalyzeResponse, TranscriptLine, ViralClip } from '../../lib/types';
import { postParts } from '../clips/postText';

/**
 * Turning an analysis into files the user can keep.
 *
 * The old app could show results but never get them out: closing the tab lost
 * every timestamp. These are pure string builders, so they can be tested
 * without a browser and the same output feeds both a download and the
 * clipboard.
 */

/** `01:23` under an hour, `1:02:03` beyond it. */
export function timestamp(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n: number) => String(n).padStart(2, '0');
  return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${pad(m)}:${pad(sec)}`;
}

/** `00:01:23,456`, the comma-separated form SRT requires. */
export function srtTimestamp(seconds: number): string {
  const total = Math.max(0, seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = Math.floor(total % 60);
  const ms = Math.round((total - Math.floor(total)) * 1000);
  const pad = (n: number, w = 2) => String(n).padStart(w, '0');
  return `${pad(h)}:${pad(m)}:${pad(s)},${pad(ms, 3)}`;
}

export type TimestampFormat = 'plain' | 'titled' | 'chapters';

/** The clip's own title, preferring a rename over the AI's suggestion. */
export function clipTitle(clip: ViralClip): string {
  return clip.custom_title?.trim() || clip.title_suggestion?.trim() || clip.title?.trim() || 'Clip';
}

/**
 * Clip times as text, in the three shapes the old app offered.
 *
 * `chapters` is the YouTube format, which requires the first entry to start
 * at 00:00 or the chapters are rejected, so one is prepended when needed.
 */
export function formatTimestamps(clips: ViralClip[], format: TimestampFormat): string {
  const sorted = [...clips].sort((a, b) => a.start_time - b.start_time);

  if (format === 'chapters') {
    const lines = sorted.map((c) => `${timestamp(c.start_time)} ${clipTitle(c)}`);
    // Built from timestamp() rather than a literal, so the intro is padded
    // the same way as every other line instead of reading '0:00' among '00:xx'.
    const first = sorted[0];
    if (!first || first.start_time >= 1) lines.unshift(`${timestamp(0)} Intro`);
    return lines.join('\n');
  }

  return sorted
    .map((c) => {
      const range = `${timestamp(c.start_time)} - ${timestamp(c.end_time)}`;
      return format === 'titled' ? `${range} | ${clipTitle(c)}` : range;
    })
    .join('\n');
}

/**
 * SRT subtitles for one clip, or the whole video when no clip is given.
 *
 * Times are rebased so the clip starts at zero, because the file is meant to
 * sit beside the exported clip, not the source video. Lines outside the clip
 * are dropped, and a line straddling an edge is trimmed to it.
 */
export function buildSrt(transcript: TranscriptLine[], clip?: ViralClip): string {
  const from = clip?.start_time ?? 0;
  const to = clip?.end_time ?? Number.POSITIVE_INFINITY;

  return transcript
    .filter((l) => l.end > from && l.start < to && l.text.trim() !== '')
    .map((l) => ({
      start: Math.max(l.start, from) - from,
      end: Math.min(l.end, to) - from,
      text: l.text.trim(),
    }))
    .filter((l) => l.end > l.start)
    .map((l, i) => `${i + 1}\n${srtTimestamp(l.start)} --> ${srtTimestamp(l.end)}\n${l.text}\n`)
    .join('\n');
}

/**
 * Nothing, as null. The backend never leaves these fields out -- every one
 * has a default, so "the AI gave nothing" arrives as `""` or `[]`, not as a
 * missing key. Writing all three as null is what lets two exports be
 * compared: a reader can test one value instead of three empty shapes.
 */
function orNull<T>(value: T | null | undefined): T | null {
  if (value === null || value === undefined || value === '') return null;
  if (Array.isArray(value) && value.length === 0) return null;
  return value;
}

/**
 * The whole analysis as JSON, formatted to be read as well as parsed.
 *
 * Every clip has the same keys whichever analysis produced it, and anything
 * the AI did not give is null (issue #128), so two exports can be diffed.
 */
export function buildJson(result: AnalyzeResponse): string {
  return JSON.stringify(
    {
      video_id: result.video_id,
      title: result.title,
      channel: result.channel ?? null,
      duration: result.duration,
      // Issue #128: which model and which clip length produced this. Two
      // exports of the same video are otherwise indistinguishable, and the
      // fallback chain means the model is not always the one requested.
      model: orNull(result.model),
      clip_range_preset: orNull(result.clip_range_preset),
      clip_range_seconds: orNull(result.clip_range_seconds),
      summary: orNull(result.summary),
      exported_at: new Date().toISOString(),
      clip_count: result.clips.length,
      clips: [...result.clips]
        .sort((a, b) => a.start_time - b.start_time)
        .map((c) => ({
          // What is shown: the user's rename when there is one.
          title: clipTitle(c),
          // What the AI wrote, kept apart from it: a renamed clip would
          // otherwise lose the title being compared.
          ai_title: orNull(c.title),
          title_options: orNull(c.title_options),
          start_time: c.start_time,
          end_time: c.end_time,
          duration: Number((c.end_time - c.start_time).toFixed(2)),
          hook_time: orNull(c.hook_time),
          virality_score: c.virality_score,
          content_type: orNull(c.content_type),
          // Issue #99: why the clip opens where it does, and the sentences
          // its bounds are anchored to. This is what says *why* a clip was
          // picked, so an export without it cannot be compared to another.
          scroll_stop_reason: orNull(c.scroll_stop_reason),
          opening_line: orNull(c.opening_line),
          new_viewer_check: orNull(c.new_viewer_check),
          payoff_line: orNull(c.payoff_line),
          ending_line: orNull(c.ending_line),
          key_quotes: orNull(c.key_quotes),
          caption_suggestion: orNull(c.caption_suggestion),
          hashtag_suggestion: orNull(c.hashtag_suggestion),
        })),
    },
    null,
    2,
  );
}

/** The analysis as Markdown, for pasting into notes or a description. */
export function buildMarkdown(result: AnalyzeResponse): string {
  const head = [
    `# ${result.title || result.video_id}`,
    '',
    `${result.clips.length} clip${result.clips.length === 1 ? '' : 's'}`,
    '',
  ];

  const body = [...result.clips]
    .sort((a, b) => a.start_time - b.start_time)
    .map((c) => {
      const parts = [
        `## ${clipTitle(c)}`,
        '',
        `- Time: ${timestamp(c.start_time)} - ${timestamp(c.end_time)}`,
        `- Score: ${c.virality_score}`,
      ];
      const { caption, hashtags } = postParts(c);
      if (caption) parts.push(`- Caption: ${caption}`);
      if (hashtags) parts.push(`- Hashtags: ${hashtags}`);
      if (c.key_quotes.length > 0) {
        parts.push('', '> ' + c.key_quotes.map((q) => q.trim()).join('\n> '));
      }
      return parts.join('\n');
    });

  return [...head, body.join('\n\n')].join('\n').trimEnd() + '\n';
}

/** Strips the characters Windows rejects, matching the backend's own rule. */
export function safeFileName(name: string, fallback = 'export'): string {
  return name.replace(/[\\/*?:"<>|]/g, '').trim() || fallback;
}

/** Hands the browser a string as a file download. */
export function downloadText(content: string, fileName: string, mime: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: `${mime};charset=utf-8` }));
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoking immediately can cancel the download in some browsers.
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
