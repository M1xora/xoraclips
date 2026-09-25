import { useState } from 'react';
import {
  BookmarkSimpleIcon,
  CaretDownIcon,
  CopyIcon,
  PlayIcon,
  ScissorsIcon,
} from '@phosphor-icons/react';
import { Button } from '../../components/ui/Button';
import type { ViralClip } from '../../lib/types';
import { formatTimecode } from '../../lib/format';
import { useLanguage } from '../../i18n';
import { postText } from './postText';

interface ClipCardProps {
  clip: ViralClip;
  index: number;
  marked: boolean;
  active: boolean;
  onToggleMark: () => void;
  onSelect: () => void;
  onPreview: () => void;
  onTrim: () => void;
  onCopy: (text: string, label: string) => void;
}

export function ClipCard({
  clip,
  index,
  marked,
  active,
  onToggleMark,
  onSelect,
  onPreview,
  onTrim,
  onCopy,
}: ClipCardProps) {
  const { t } = useLanguage();
  const [open, setOpen] = useState(false);
  const [captionOpen, setCaptionOpen] = useState(false);
  const post = postText(clip);
  const caption = clip.caption_suggestion?.trim();
  const hashtags = clip.hashtag_suggestion?.trim();
  const duration = Math.round(clip.end_time - clip.start_time);
  const range = `${formatTimecode(clip.start_time)} - ${formatTimecode(clip.end_time)}`;
  const strong = clip.virality_score >= 90;

  return (
    <article
      onClick={onSelect}
      className={`panel cursor-pointer p-4 transition-colors
        ${active ? 'border-accent' : 'hover:border-ink-faint'}`}
    >
      <div className="flex items-start gap-3">
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onToggleMark();
          }}
          aria-pressed={marked}
          aria-label={marked ? t.results.unmark(index + 1) : t.results.mark(index + 1)}
          className={`pressable mt-0.5 grid size-6 shrink-0 place-items-center rounded
            ${marked ? 'bg-accent text-on-accent' : 'bg-surface-2 text-ink-faint hover:text-ink'}`}
        >
          <BookmarkSimpleIcon size={13} weight={marked ? 'fill' : 'regular'} />
        </button>

        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-medium leading-snug">{clip.title}</h3>

          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="tabular font-mono text-xs text-ink-dim">{range}</span>
            <span className="tabular text-xs text-ink-faint">{duration}s</span>
            <span
              className={`tabular rounded px-1.5 py-0.5 font-mono text-[0.8rem] font-semibold
                ${strong ? 'bg-accent-muted text-ink' : 'bg-surface-2 text-ink-dim'}`}
            >
              {clip.virality_score}
            </span>
          </div>

          {clip.key_quotes?.length > 0 && (
            <p className="mt-2 border-l-2 border-hairline pl-2.5 text-xs italic text-ink-dim">
              {clip.key_quotes[0]}
            </p>
          )}

          {post && (
            // The caption Gemini wrote for posting, ready to paste (#49).
            <div
              onClick={(e) => e.stopPropagation()}
              className="mt-3 cursor-default rounded-md bg-surface-2 p-2.5"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-[0.7rem] font-medium uppercase tracking-wide text-ink-faint">
                  {t.results.postCaption}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onCopy(post, t.results.postCopied)}
                  icon={<CopyIcon size={13} />}
                >
                  {t.results.copyPost}
                </Button>
              </div>
              {caption && (
                <button
                  type="button"
                  aria-expanded={captionOpen}
                  aria-label={captionOpen ? undefined : t.results.showFullCaption}
                  onClick={() => setCaptionOpen((v) => !v)}
                  className={`mt-1 w-full whitespace-pre-line text-left text-xs leading-relaxed
                    text-ink-dim ${captionOpen ? '' : 'line-clamp-3'}`}
                >
                  {caption}
                </button>
              )}
              {hashtags && (
                <p className="mt-1.5 break-words text-xs text-ink-faint">{hashtags}</p>
              )}
            </div>
          )}

          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <Button
              variant="secondary"
              size="sm"
              onClick={(e) => {
                e.stopPropagation();
                onPreview();
              }}
              icon={<PlayIcon size={13} weight="fill" />}
            >
              {t.results.preview}
            </Button>
            <Button
              variant="teal"
              size="sm"
              onClick={(e) => {
                e.stopPropagation();
                onTrim();
              }}
              icon={<ScissorsIcon size={13} />}
            >
              {t.results.trim}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={(e) => {
                e.stopPropagation();
                onCopy(range, t.results.copied);
              }}
              icon={<CopyIcon size={13} />}
            >
              {t.results.copy}
            </Button>

            {clip.transcript && (
              <button
                type="button"
                aria-expanded={open}
                onClick={(e) => {
                  e.stopPropagation();
                  setOpen((v) => !v);
                }}
                className="pressable ml-auto flex items-center gap-1 rounded px-1.5 py-1
                  text-xs text-ink-faint hover:text-ink"
              >
                {t.results.transcript}
                <CaretDownIcon
                  size={11}
                  className={`transition-transform ${open ? 'rotate-180' : ''}`}
                />
              </button>
            )}
          </div>

          {open && clip.transcript && (
            <p className="mt-3 max-h-40 overflow-y-auto border-t border-hairline pt-3
              text-xs leading-relaxed text-ink-dim">
              {clip.transcript}
            </p>
          )}
        </div>
      </div>
    </article>
  );
}
