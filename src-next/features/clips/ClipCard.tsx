import { useEffect, useRef, useState } from 'react';
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
import { postParts, postText } from './postText';
import { clipRangeFit } from './clipRange';

interface ClipCardProps {
  clip: ViralClip;
  /** [shortest, longest] of the chosen preset (#94); absent on older analyses. */
  clipRange?: [number, number] | null;
  /** The preset's label ("30s", "2m"), shown with the range. */
  clipPreset?: string | null;
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
  clipRange,
  clipPreset,
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
  const [captionClamped, setCaptionClamped] = useState(false);
  const captionRef = useRef<HTMLParagraphElement>(null);
  const post = postText(clip);
  const { caption, hashtags } = postParts(clip);

  // "Show more" only when the 3-line clamp actually hides text. The observer
  // also fires once right away, and again when the card width changes.
  useEffect(() => {
    const el = captionRef.current;
    if (!el || captionOpen || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => {
      setCaptionClamped(el.scrollHeight > el.clientHeight + 1);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [caption, captionOpen]);
  const duration = Math.round(clip.end_time - clip.start_time);
  const range = `${formatTimecode(clip.start_time)} - ${formatTimecode(clip.end_time)}`;
  const strong = clip.virality_score >= 90;
  // Issue #94: a clip outside the preset range keeps its length; the card
  // only says by how much, and Trim stays available. The exact length is
  // compared, not the rounded one: a 40.4s clip is over a 20-40s preset even
  // though the card shows it as 40s.
  const outside = clipRangeFit(clip.end_time - clip.start_time, clipRange);
  const outsideText = outside
    ? (outside.status === 'over' ? t.results.lengthOver : t.results.lengthUnder)(
        // Never "0s over": a clip a fraction past the edge is still past it.
        Math.max(1, Math.round(outside.off)),
        clipPreset ?? `${outside.shortest}-${outside.longest}s`,
        outside.shortest, outside.longest)
    : '';

  return (
    <article
      onClick={onSelect}
      className={`panel cursor-pointer p-4 transition-[background-color,box-shadow]
        ${active ? 'bg-accent-muted shadow-brutal-lg' : 'hover:bg-surface-2'}`}
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
            ${marked
              ? 'border-2 border-line bg-accent text-on-accent'
              : 'border-2 border-hairline bg-surface text-ink-faint hover:text-ink'}`}
        >
          <BookmarkSimpleIcon size={13} weight={marked ? 'fill' : 'regular'} />
        </button>

        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-extrabold leading-snug">{clip.title}</h3>

          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="tabular font-mono text-xs text-ink-dim">{range}</span>
            <span className={`tabular text-xs ${outside ? 'font-semibold text-ink' : 'text-ink-faint'}`}>
              {duration}s
            </span>
            {outside && (
              <span className="tabular rounded border-2 border-hairline bg-surface-2 px-1.5 py-0.5 font-mono text-[0.8rem] font-semibold text-ink-dim">
                {outsideText}
              </span>
            )}
            <span
              className={`tabular rounded px-1.5 py-0.5 font-mono text-[0.8rem] font-semibold
                ${strong
                  ? '-rotate-3 border-2 border-line bg-accent text-on-accent shadow-brutal-sm'
                  : 'border-2 border-hairline bg-surface-2 text-ink-dim'}`}
            >
              {clip.virality_score}
            </span>
          </div>

          {/* Issue #94: why the clip is this long, as text rather than a
              tooltip, which never opens on a phone. */}
          {outside && (
            <p className="mt-1 text-[0.7rem] leading-snug text-ink-faint">{t.results.lengthOutsideHint}</p>
          )}

          {clip.key_quotes?.length > 0 && (
            <p className="mt-2 border-l-4 border-accent pl-2.5 text-xs italic text-ink-dim">
              {clip.key_quotes[0]}
            </p>
          )}

          {post && (
            // The caption Gemini wrote for posting, ready to paste (#49).
            <div className="mt-3 rounded-md border-2 border-hairline p-2.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[0.7rem] font-medium uppercase tracking-wide text-ink-faint">
                  {t.results.postCaption}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={(e) => {
                    e.stopPropagation();
                    onCopy(post, t.results.postCopied);
                  }}
                  icon={<CopyIcon size={13} />}
                >
                  {t.results.copyPost}
                </Button>
              </div>
              {caption && (
                <p
                  ref={captionRef}
                  className={`mt-1 whitespace-pre-line text-xs leading-relaxed text-ink-dim
                    ${captionOpen ? '' : 'line-clamp-3'}`}
                >
                  {caption}
                </p>
              )}
              {caption && (captionClamped || captionOpen) && (
                <button
                  type="button"
                  aria-expanded={captionOpen}
                  onClick={(e) => {
                    e.stopPropagation();
                    setCaptionOpen((v) => !v);
                  }}
                  className="pressable mt-1 rounded text-xs font-medium text-ink-faint hover:text-ink"
                >
                  {captionOpen ? t.results.showLessCaption : t.results.showFullCaption}
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
