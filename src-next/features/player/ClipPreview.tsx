import { useEffect, useMemo } from 'react';
import {
  ArrowsOutSimpleIcon,
  PauseIcon,
  PlayIcon,
  SpeakerSimpleHighIcon,
  SpeakerSimpleSlashIcon,
  UserFocusIcon,
} from '@phosphor-icons/react';
import { useYouTubePlayer, type ClipBounds } from '../../hooks/useYouTubePlayer';
import { faceOffsetPercent, useFaceBox } from '../../hooks/useFaceBox';
import { usePreviewAudio } from '../../hooks/usePreviewAudio';
import { CaptionOverlay } from '../studio/CaptionOverlay';
import { PreviewTitle } from './PreviewTitle';
import { useCaptionChunks } from '../../hooks/useCaptionChunks';
import { useLanguage } from '../../i18n';
import { formatTimecode } from '../../lib/format';
import { api } from '../../api/client';
import {
  CANVAS_H,
  CANVAS_W,
  hasBars,
  PIP_POS,
  PIP_SIZE,
  SPLIT_LAYOUT,
  VIDEO_BOX,
} from './canvas';
import type {
  AspectRatioOption,
  BackgroundStyle,
  CaptionFont,
  CaptionStyle,
  FontSizeOption,
  StreamerPreset,
  SubtitlePositionMode,
  TextCaseOption,
  TranscriptLine,
  ViralClip,
} from '../../lib/types';

/** Preview canvas width in px; the frame is always this shape. */
const FRAME_W = 288;
const FRAME_H = Math.round((FRAME_W * CANVAS_H) / CANVAS_W);

/** Export pixels to preview pixels. */
const SCALE = FRAME_W / CANVAS_W;

/** Size the 16:9 source needs so it covers a box in both directions. */
function coverSize(boxW: number, boxH: number) {
  const width = Math.max(boxW, boxH * (16 / 9));
  return { width, height: width * (9 / 16) };
}

interface ClipPreviewProps {
  videoId: string;
  clip: ViralClip;
  transcript?: TranscriptLine[];

  aspectRatio?: AspectRatioOption;
  streamerPreset?: StreamerPreset;

  /** Uploaded background music, so the preview can be heard, not just seen. */
  bgmUrl?: string | null;
  bgmEnabled?: boolean;
  bgmVolume?: number;
  bgmStartOffset?: number;
  sfxUrl?: string | null;
  sfxEnabled?: boolean;
  sfxVolume?: number;
  /** Whether preview sound is on; the video itself stays muted. */
  soundOn?: boolean;
  onToggleSound?: () => void;
  soundLabel?: string;
  backgroundStyle?: BackgroundStyle;
  enableFaceTracking?: boolean;

  title?: string;
  titleYPercent?: number;
  /** Title size preset; the font size follows the renderer's (issue #19). */
  titleFontSize?: FontSizeOption;

  watermarkEnabled?: boolean;
  watermarkType?: 'image' | 'text';
  watermarkUrl?: string | null;
  watermarkText?: string;
  watermarkSize?: number;
  watermarkOpacity?: number;
  watermarkX?: number;
  watermarkY?: number;

  captionStyle?: CaptionStyle;
  captionFont?: CaptionFont;
  fontSize?: FontSizeOption;
  textCase?: TextCaseOption;
  subtitlePositionMode?: SubtitlePositionMode;
  subtitleYPercent?: number;
  subtitleCenterYPercent?: number;

  autoPlay?: boolean;
  loop?: boolean;
  label: string;
  faceTrackingLabel: string;
}

/**
 * Vertical preview of a clip, as close to the export as a browser can get.
 *
 * Shows the crop, the title, word-level captions and, when the backend finds
 * a face, shifts the crop so the speaker stays in frame.
 */
export function ClipPreview({
  videoId,
  clip,
  transcript,
  aspectRatio = '9:16',
  streamerPreset = 'none',
  bgmUrl = null,
  bgmEnabled = false,
  bgmVolume = 25,
  bgmStartOffset = 0,
  sfxUrl = null,
  sfxEnabled = false,
  sfxVolume = 100,
  soundOn = false,
  onToggleSound,
  soundLabel,
  backgroundStyle = 'black',
  enableFaceTracking = true,
  title,
  titleYPercent = 17,
  titleFontSize = 'medium',
  watermarkEnabled = false,
  watermarkType = 'image',
  watermarkUrl = null,
  watermarkText = '',
  watermarkSize = 20,
  watermarkOpacity = 80,
  watermarkX = 88,
  watermarkY = 8,
  captionStyle = 'viral_pop',
  captionFont = 'Outfit',
  fontSize = 'medium',
  textCase = 'uppercase',
  subtitlePositionMode = 'bottom',
  subtitleYPercent = 21,
  subtitleCenterYPercent = 50,
  autoPlay = false,
  loop = true,
  label,
  faceTrackingLabel,
}: ClipPreviewProps) {
  // The canvas never changes shape; the video box inside it does.
  //
  // split_top_cam is the exception: it stacks two boxes and ignores the plain
  // VIDEO_BOX altogether (video_engine.py:1305-1370), so the geometry comes
  // from SPLIT_LAYOUT instead.
  const split = streamerPreset === 'split_top_cam';
  const layout = SPLIT_LAYOUT[aspectRatio];

  const videoBox = VIDEO_BOX[aspectRatio];
  const videoW = split ? Math.round(layout.w * SCALE) : FRAME_W;
  const videoH = split ? Math.round(layout.h * SCALE) : Math.round(videoBox.h * SCALE);
  const videoX = split ? Math.round(layout.x * SCALE) : 0;
  const videoY = split ? Math.round(layout.y * SCALE) : Math.round(videoBox.y * SCALE);
  const cover = coverSize(videoW, videoH);

  const bounds: ClipBounds = useMemo(
    () => ({ start: clip.start_time, end: clip.end_time }),
    [clip.start_time, clip.end_time],
  );

  const { hostRef, ready, playing, currentTime, toggle, play } = useYouTubePlayer({
    videoId,
    bounds,
    loop,
    muted: true,
    controls: false,
    pollMs: 120,
  });

  // Sample the face once per clip, at its midpoint, rather than per frame.
  const sampleAt = Math.round((clip.start_time + clip.end_time) / 2);
  // The backend detects a face for these presets regardless of ratio
  // (video_engine.py:1590), so the preview follows the same rule.
  const tracks =
    streamerPreset !== 'none' || (enableFaceTracking && aspectRatio === '9:16');
  const { box } = useFaceBox(videoId, sampleAt, tracks);

  // Captions come from the backend so they match the export exactly.
  const { t } = useLanguage();
  const captions = useCaptionChunks(
    transcript,
    clip.start_time,
    clip.end_time,
    textCase,
    captionStyle !== 'none',
  );
  const captionNote =
    captions.status === 'renderOnly'
      ? t.studio.captionsRenderOnly
      : captions.status === 'error'
        ? t.studio.captionsUnavailable
        : null;
  const offsetPct = faceOffsetPercent(box, videoW, cover.width);

  useEffect(() => {
    if (autoPlay && ready) play();
  }, [autoPlay, ready, clip.id, play]);

  // A backdrop is only visible where there is bar to fill. Plain 9:16 is full
  // bleed and has none, but 9:16 with a split does: the stacked pair is only
  // 540px wide in a 1080px canvas, so 270px of bar sits either side.
  const showBackdrop =
    backgroundStyle === 'blurred' && (split ? layout.x > 0 || layout.y > 0 : hasBars(aspectRatio));
  const backdropUrl = api.clipFrameUrl(videoId, sampleAt);

  const elapsed = Math.max(0, currentTime - clip.start_time);
  const total = Math.max(1, clip.end_time - clip.start_time);
  const progress = Math.min(100, (elapsed / total) * 100);

  const hasAudio = (bgmEnabled && !!bgmUrl) || (sfxEnabled && !!sfxUrl);

  // The YouTube iframe stays muted, so what is audible here is the music and
  // the hook sound as the renderer would mix them.
  usePreviewAudio({
    bgmUrl,
    bgmEnabled,
    bgmVolume,
    bgmStartOffset,
    sfxUrl,
    sfxEnabled,
    sfxVolume,
    playing,
    elapsed,
    duration: total,
    enabled: soundOn,
  });

  // The iframe is oversized and centred inside the video box, which clips it.
  const cropStyle = {
    position: 'absolute' as const,
    width: `${cover.width}px`,
    height: `${cover.height}px`,
    left: '50%',
    top: '50%',
    transform: `translate(calc(-50% + ${offsetPct}%), -50%)`,
    transition: 'transform 300ms ease',
  };

  return (
    <div className="flex flex-col items-center gap-2">
      {/* The canvas: always 9:16, whatever the video ratio is. */}
      <div
        className="relative shrink-0 overflow-hidden rounded-xl border border-hairline bg-black"
        style={{ width: FRAME_W, height: FRAME_H }}
      >
        {/* Blurred backdrop fills the bars the padding leaves behind. The
            renderer blurs the clip's own frames, so this samples a frame from
            the clip rather than the video's thumbnail. */}
        {showBackdrop && (
          <div
            className="absolute inset-0 scale-110 bg-cover bg-center blur-xl saturate-150"
            style={{ backgroundImage: `url(${backdropUrl})` }}
            aria-hidden="true"
          />
        )}

        {/* The video box. Anything outside it is a black bar, exactly as
            ffmpeg's pad filter produces. With split_top_cam this is the
            LOWER box, the gameplay feed; the facecam sits above it. */}
        <div
          className="absolute overflow-hidden"
          style={{
            top: split ? videoY + videoH : videoY,
            left: videoX,
            width: videoW,
            height: videoH,
          }}
        >
          <div
            ref={hostRef}
            style={cropStyle}
            className="[&>div]:size-full [&_iframe]:size-full"
            aria-hidden={!ready}
          />
        </div>

        {/* A single YouTube iframe cannot be shown in two places at once, so
            the facecam box shows the clip's own frame cropped to the face
            rather than a second live player. It is the right geometry with a
            still image, not a fake live feed. */}
        {split && (
          <div
            className="absolute overflow-hidden border-b border-white/10"
            style={{ top: videoY, left: videoX, width: videoW, height: videoH }}
          >
            <div
              className="size-full bg-cover"
              style={{
                backgroundImage: `url(${backdropUrl})`,
                backgroundPosition: `${Math.round((box?.cx ?? 0.5) * 100)}% ${Math.round(
                  (box?.cy ?? 0.35) * 100,
                )}%`,
                backgroundSize: '154%',
              }}
              aria-hidden="true"
            />
          </div>
        )}

        {/* pip_corner keeps the main video and drops a 320x240 box on top. */}
        {streamerPreset === 'pip_corner' && (
          <div
            className="absolute overflow-hidden rounded-[2px] border border-white/25 shadow-lg"
            style={{
              left: Math.round(PIP_POS[aspectRatio].x * SCALE),
              top: Math.round(PIP_POS[aspectRatio].y * SCALE),
              width: Math.round(PIP_SIZE.w * SCALE),
              height: Math.round(PIP_SIZE.h * SCALE),
            }}
          >
            <div
              className="size-full bg-cover"
              style={{
                backgroundImage: `url(${backdropUrl})`,
                backgroundPosition: `${Math.round((box?.cx ?? 0.5) * 100)}% ${Math.round(
                  (box?.cy ?? 0.35) * 100,
                )}%`,
                backgroundSize: '200%',
              }}
              aria-hidden="true"
            />
          </div>
        )}

        {!ready && <div className="skeleton absolute inset-0" aria-hidden="true" />}

        {title && (
          <PreviewTitle
            text={title}
            sizePreset={titleFontSize}
            font={captionFont}
            scale={SCALE}
            topPercent={titleYPercent}
          />
        )}

        <CaptionOverlay
          chunks={captions.chunks}
          currentTime={currentTime}
          style={captionStyle}
          font={captionFont}
          fontSize={fontSize}
          positionMode={subtitlePositionMode}
          bottomPercent={subtitleYPercent}
          centerPercent={subtitleCenterYPercent}
          scale={1}
        />

        {captionNote && (
          <div
            className="pointer-events-none absolute inset-x-0 px-3 text-center"
            style={
              subtitlePositionMode === 'center'
                ? { top: `${subtitleCenterYPercent}%`, transform: 'translateY(-50%)' }
                : { bottom: `${subtitleYPercent}%` }
            }
          >
            <span className="rounded bg-black/70 px-2 py-1 text-[0.7rem] font-medium text-white">
              {captionNote}
            </span>
          </div>
        )}

        {/* Watermark. x and y are the centre point, matching the renderer. */}
        {watermarkEnabled && (watermarkType === 'text' ? watermarkText : watermarkUrl) && (
          <div
            className="pointer-events-none absolute"
            style={{
              left: `${watermarkX}%`,
              top: `${watermarkY}%`,
              transform: 'translate(-50%, -50%)',
              opacity: watermarkOpacity / 100,
            }}
          >
            {watermarkType === 'image' && watermarkUrl ? (
              <img
                src={watermarkUrl}
                alt=""
                style={{ width: `${Math.round((FRAME_W * watermarkSize) / 100)}px`, height: 'auto' }}
              />
            ) : (
              <span
                className="whitespace-nowrap rounded bg-black/45 px-1.5 py-0.5 font-semibold text-white"
                // Backend: font = 180 * (size/100) on a 1080-wide canvas
                // (video_engine.py:1657). Scaling that by SCALE keeps the
                // preview on the same curve; the old 56 * (FRAME_W/320)
                // constant ran about 5% large at every size.
                style={{
                  fontSize: `${Math.max(7, Math.round(180 * (watermarkSize / 100) * SCALE))}px`,
                }}
              >
                {watermarkText}
              </span>
            )}
          </div>
        )}

        <button
          type="button"
          onClick={toggle}
          disabled={!ready}
          aria-label={label}
          className="absolute inset-0 grid place-items-center focus-visible:outline-offset-[-2px]"
        >
          {!playing && ready && (
            <span className="grid size-12 place-items-center rounded-full bg-black/55 backdrop-blur-sm">
              <PlayIcon size={20} weight="fill" className="ml-0.5 text-white" />
            </span>
          )}
        </button>

        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-1 bg-white/15">
          <div className="h-full bg-accent" style={{ width: `${progress}%` }} />
        </div>
      </div>

      <div className="flex items-center justify-between gap-2" style={{ width: FRAME_W }}>
        <span className="flex items-center gap-1.5 text-[0.8rem] text-ink-faint">
          <ArrowsOutSimpleIcon size={12} />
          {aspectRatio}
          {box?.found && (
            <span className="flex items-center gap-1 text-teal-text" title={faceTrackingLabel}>
              <UserFocusIcon size={12} weight="bold" />
            </span>
          )}
        </span>
        <span className="tabular font-mono text-[0.8rem] text-ink-dim">
          {formatTimecode(elapsed)} / {formatTimecode(total)}
        </span>
        <span className="flex items-center gap-0.5">
          {/* Only offered when there is something to hear: the video track
              itself stays muted, so without an uploaded asset this would be a
              button that does nothing. */}
          {onToggleSound && hasAudio && (
            <button
              type="button"
              onClick={onToggleSound}
              aria-pressed={soundOn}
              className={`pressable grid size-6 place-items-center rounded hover:bg-surface-2
                ${soundOn ? 'text-teal-text' : 'text-ink-faint hover:text-ink'}`}
              aria-label={soundLabel}
              title={soundLabel}
            >
              {soundOn ? (
                <SpeakerSimpleHighIcon size={12} weight="fill" />
              ) : (
                <SpeakerSimpleSlashIcon size={12} />
              )}
            </button>
          )}

          <button
            type="button"
            onClick={toggle}
            disabled={!ready}
            className="pressable grid size-6 place-items-center rounded text-ink-dim
              hover:bg-surface-2 hover:text-ink disabled:opacity-40"
            aria-label={label}
          >
            {playing ? <PauseIcon size={12} weight="fill" /> : <PlayIcon size={12} weight="fill" />}
          </button>
        </span>
      </div>
    </div>
  );
}
