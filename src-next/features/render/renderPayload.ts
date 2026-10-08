import type { AnalyzeResponse, ViralClip } from '../../lib/types';
import type { StudioState } from '../studio/studioReducer';
import { effectiveTitle } from '../clips/clipIdentity';

/**
 * Builds the body for POST /api/render-batch.
 *
 * The shape is dictated by backend/routes_render.py: RenderBatchRequest and
 * RenderSettingsModel. The backend downloads the video from `video_id` only
 * (#70); a URL is not sent. Two things are easy to get wrong and fail
 * silently rather than loudly:
 *
 *  - `transcript` is a TOP-LEVEL key, a sibling of `settings`, not a field
 *    inside it. Omit it and the render still succeeds, but the backend falls
 *    back to running Whisper per clip: slower, and different subtitles.
 *
 *  - Each clip needs `custom_title`, which the backend reads at lines 2274
 *    and 2463 when naming the output.
 */

export interface RenderBatchPayload {
  video_id: string;
  clips: Record<string, unknown>[];
  settings: Record<string, unknown>;
  transcript: AnalyzeResponse['transcript'];
}

export function buildRenderPayload(
  result: AnalyzeResponse,
  selected: ViralClip[],
  studio: StudioState,
  customTitles: Record<string, string>,
): RenderBatchPayload {
  return {
    video_id: result.video_id,

    clips: selected.map((clip) => ({
      ...clip,
      custom_title: effectiveTitle(clip, customTitles),
    })),

    settings: {
      aspect_ratio: studio.aspectRatio,
      background_style: studio.backgroundStyle,
      enable_face_tracking: studio.enableFaceTracking,
      // Issue #105: null means the backend follows the detected face.
      cam_zoom: studio.camZoom,
      cam_center_x: studio.camCenterX,
      cam_center_y: studio.camCenterY,
      streamer_preset: studio.streamerPreset,

      title_text: selected.length === 1 ? effectiveTitle(selected[0], customTitles) : undefined,
      title_prefix: studio.titlePrefix,
      title_suffix: studio.titleSuffix,
      title_position: studio.titlePosition,
      title_duration: studio.titleDuration,
      title_font_size: studio.titleFontSize,
      title_y_percent: studio.titleYPercent,

      subtitles_enabled: studio.captionStyle !== 'none',
      caption_style: studio.captionStyle,
      caption_font: studio.captionFont,
      font_size: studio.fontSize,
      text_case: studio.textCase,
      subtitle_y_percent: studio.subtitleYPercent,
      subtitle_position_mode: studio.subtitlePositionMode,
      subtitle_center_y_percent: studio.subtitleCenterYPercent,

      bgm_enabled: studio.bgmEnabled && Boolean(studio.bgmFilePath),
      bgm_file_path: studio.bgmFilePath,
      bgm_volume: studio.bgmVolume,
      bgm_start_offset: studio.bgmStartOffset,

      hook_sfx_enabled: studio.hookSfxEnabled && Boolean(studio.hookSfxFilePath),
      hook_sfx_file_path: studio.hookSfxFilePath,
      hook_sfx_volume: studio.hookSfxVolume,

      original_audio_volume: studio.originalAudioVolume,

      watermark_enabled: studio.watermarkEnabled,
      watermark_type: studio.watermarkType,
      watermark_file_path: studio.watermarkFilePath,
      watermark_text: studio.watermarkText || null,
      watermark_size: studio.watermarkSize,
      watermark_opacity: studio.watermarkOpacity,
      watermark_x: studio.watermarkX,
      watermark_y: studio.watermarkY,

      hardware_accel: studio.hardwareAccel,
      file_name_prefix: studio.fileNamePrefix,
      file_name_suffix: studio.fileNameSuffix,
    },

    // Top level, deliberately. See the note above.
    transcript: result.transcript,
  };
}

/**
 * Output file name for a finished clip.
 *
 * The original repeated this logic in two places (ClipStudioSection.tsx
 * 3250-3289 and 3420-3458) that had to stay in step. One copy here.
 */
export function outputFileName(
  title: string,
  prefix: string,
  suffix: string,
  seen: Map<string, number>,
): string {
  const clean = title.replace(/[\\/*?:"<>|]/g, '').trim() || 'clip';
  const base = `${prefix}${clean}${suffix}`.trim() || clean;

  const count = seen.get(base) ?? 0;
  seen.set(base, count + 1);

  return count === 0 ? `${base}.mp4` : `${base} (${count}).mp4`;
}
