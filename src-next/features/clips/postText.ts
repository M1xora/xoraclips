import type { ViralClip } from '../../lib/types';

type PostFields = Pick<ViralClip, 'caption_suggestion' | 'hashtag_suggestion'>;

/**
 * The AI caption and hashtags for posting a clip (#49), trimmed; '' for a
 * missing part (analyses cached before the backend wrote them, or null from
 * an imported JSON export). The one place both the card and the exports read.
 */
export function postParts(clip: PostFields): { caption: string; hashtags: string } {
  return {
    caption: clip.caption_suggestion?.trim() ?? '',
    hashtags: clip.hashtag_suggestion?.trim() ?? '',
  };
}

/** The text to paste when posting: caption, a blank line, hashtags; '' when both are missing. */
export function postText(clip: PostFields): string {
  const { caption, hashtags } = postParts(clip);
  return [caption, hashtags].filter(Boolean).join('\n\n');
}
