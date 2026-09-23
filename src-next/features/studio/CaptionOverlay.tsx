import { Fragment } from 'react';
import { activeWordIndex, CAPTION_THEMES, chunkAt, type CaptionChunk } from './captions';
import { subtitleFontPx } from './derive';
import type {
  CaptionFont,
  CaptionStyle,
  FontSizeOption,
  SubtitlePositionMode,
} from '../../lib/types';

/** Web-safe stacks for the eight caption fonts the renderer offers. */
const FONT_STACKS: Record<CaptionFont, string> = {
  Outfit: "'Geist', system-ui, sans-serif",
  Montserrat: "'Geist', system-ui, sans-serif",
  Inter: "'Geist', system-ui, sans-serif",
  Impact: "Impact, 'Arial Black', sans-serif",
  'Bebas Neue': "'Arial Narrow', 'Geist', sans-serif",
  Anton: "'Arial Black', 'Geist', sans-serif",
  Poppins: "'Geist', system-ui, sans-serif",
  'Arial Black': "'Arial Black', sans-serif",
};

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
  /** Preview frames are smaller than the 1080x1920 export. */
  scale?: number;
}

/**
 * Word-level captions drawn over the preview.
 *
 * Draws the backend's chunks verbatim: the text is already cleaned and
 * cased, and each word's highlight window is the one the .ass file uses.
 * The spoken word is lifted in the style's accent colour while the rest of
 * the chunk stays white, which is the effect the ASS renderer produces.
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
  const sizePx = subtitleFontPx(fontSize) * scale;

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
          letterSpacing: '0.03em',
          textShadow: shadow,
          maxWidth: '96%',
        }}
      >
        {chunk.words.map((word, i) => (
          <Fragment key={`${word.start}-${i}`}>
            {/* The space sits between the word boxes: inside an inline-block
                a trailing space is dropped, and the words run together (#17). */}
            {i > 0 && ' '}
            <span
              data-active={i === activeIdx ? 'true' : undefined}
              style={{
                color: i === activeIdx ? theme.accent : theme.base,
                // A slight lift on the spoken word, the way the karaoke
                // effect reads in the export.
                display: 'inline-block',
                transform: i === activeIdx ? 'scale(1.08)' : 'none',
                transition: 'transform 90ms ease, color 90ms ease',
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
