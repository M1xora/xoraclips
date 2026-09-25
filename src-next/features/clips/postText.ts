import type { ViralClip } from '../../lib/types';

/**
 * The text to paste when posting a clip (#49): the AI caption, a blank line,
 * then the hashtags. Either part may be missing (analyses cached before the
 * backend wrote them); '' when both are, so the card can hide the block.
 */
export function postText(
  clip: Pick<ViralClip, 'caption_suggestion' | 'hashtag_suggestion'>,
): string {
  const caption = clip.caption_suggestion?.trim() ?? '';
  const hashtags = clip.hashtag_suggestion?.trim() ?? '';
  return [caption, hashtags].filter(Boolean).join('\n\n');
}
