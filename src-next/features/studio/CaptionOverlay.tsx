import { Fragment } from 'react';
import { activeWordIndex, CAPTION_THEMES, chunkAt, type CaptionChunk } from './captions';
import { subtitleExportPx } from './derive';
import { FONT_STACKS, LIBASS_EM_PER_FONTSIZE } from './fonts';
import type {
  CaptionFont,
  CaptionStyle,
  FontSizeOption,
  SubtitlePositionMode,
} from '../../lib/types';

interface CaptionOverlayProps {
  /** Chunks from the backend, in absolute source-video time. */
  chunks: CaptionChunk[];
  /** Absolute time in the source video. */
  currentTime: number;

  style: CaptionStyle;
  font: CaptionFont;
  fontSize: FontSizeOption;
  positionMode: SubtitlePositionMode;
  /** Percent from the bottom, for bottom mode. */
  bottomPercent: number;
  /** Percent from the top, for centre mode. */
  centerPercent: number;
  /** Export pixels to preview pixels (preview width / 1080). */
  scale?: number;
}

/**
 * Word-level captions drawn over the preview.
 *
 * Draws the backend's chunks verbatim: the text is already cleaned and
 * cased, and each word's highlight window is the one the .ass file uses.
 * The spoken word takes the style's accent colour while the rest of the
 * chunk stays white, which is the effect the ASS renderer produces.
 */
export function CaptionOverlay({
  chunks,
  currentTime,
  style,
  font,
  fontSize,
  positionMode,
  bottomPercent,
  centerPercent,
  scale = 1,
}: CaptionOverlayProps) {
  if (style === 'none' || chunks.length === 0) return null;

  const chunk = chunkAt(chunks, currentTime);
  if (!chunk) return null;

  const theme = CAPTION_THEMES[style];
  const activeIdx = activeWordIndex(chunk, currentTime);
  // The em libass really draws for this font and preset, in preview px (#22).
  const sizePx = subtitleExportPx(fontSize) * LIBASS_EM_PER_FONTSIZE[font] * scale;

  const position =
    positionMode === 'center'
      ? { top: `${centerPercent}%`, transform: 'translateY(-50%)' }
      : { bottom: `${bottomPercent}%` };

  const shadow = [
    '0 0 2px #000',
    '0 1px 3px rgba(0,0,0,.95)',
    '0 0 5px rgba(0,0,0,.8)',
    theme.glow,
  ]
    .filter(Boolean)
    .join(', ');

  return (
    <div
      className="pointer-events-none absolute inset-x-0 px-2 text-center"
      style={position}
      aria-hidden="true"
    >
      <span
        className="inline-block font-extrabold leading-tight"
        style={{
          fontFamily: FONT_STACKS[font],
          fontSize: `${sizePx}px`,
          // No extra letter spacing: SubStyle has Spacing 0 (#22).
          textShadow: shadow,
          maxWidth: '96%',
        }}
      >
        {chunk.words.map((word, i) => (
          <Fragment key={`${word.start}-${i}`}>
            {/* The space sits between the word spans, never inside one (#17). */}
            {i > 0 && ' '}
            <span
              data-active={i === activeIdx ? 'true' : undefined}
              style={{
                // Colour only, like the export: a scaled word grew over the
                // spaces beside it and looked glued to its neighbours (#17).
                color: i === activeIdx ? theme.accent : theme.base,
                transition: 'color 90ms ease',
              }}
            >
              {word.text}
            </span>
          </Fragment>
        ))}
      </span>
    </div>
  );
}
