import { describe, expect, it } from 'vitest';
import { buildRenderPayload, outputFileName } from './renderPayload';
import { initialStudioState } from '../studio/studioReducer';
import type { AnalyzeResponse, ViralClip } from '../../lib/types';

/**
 * Every field RenderSettingsModel declares, read off backend/main.py:2180.
 * A field the backend expects but the payload omits falls back to the
 * backend default without any error, which is exactly the kind of silent
 * mismatch this guards against.
 */
const BACKEND_SETTINGS_FIELDS = [
  'aspect_ratio', 'background_style', 'enable_face_tracking', 'streamer_preset',
  'title_text', 'title_prefix', 'title_suffix', 'file_name_prefix', 'file_name_suffix',
  'title_position', 'title_duration', 'subtitles_enabled', 'caption_style', 'caption_font',
  'font_size', 'title_font_size', 'text_case', 'title_y_percent', 'subtitle_y_percent',
  'subtitle_position_mode', 'subtitle_center_y_percent', 'bgm_enabled', 'bgm_file_path',
  'bgm_volume', 'bgm_start_offset', 'hook_sfx_enabled', 'hook_sfx_file_path',
  'hook_sfx_volume', 'original_audio_volume', 'watermark_enabled', 'watermark_type',
  'watermark_file_path', 'watermark_text', 'watermark_size', 'watermark_opacity',
  'watermark_x', 'watermark_y', 'hardware_accel',
  'cam_zoom', 'cam_center_x', 'cam_center_y',
] as const;

function clip(over: Partial<ViralClip> = {}): ViralClip {
  return {
    id: 'clip-1',
    title: 'Judul asli',
    start_time: 10,
    end_time: 40,
    virality_score: 90,
    key_quotes: [],
    transcript: 'isi transkrip',
    ...over,
  };
}

function result(over: Partial<AnalyzeResponse> = {}): AnalyzeResponse {
  return {
    video_id: 'abc12345678',
    title: 'Video',
    duration: 600,
    heatmap: [],
    summary: '',
    clips: [clip()],
    transcript: [{ start: 0, end: 5, text: 'halo' }],
    ...over,
  };
}

describe('settings contract', () => {
  it('sends every field the backend declares', () => {
    const payload = buildRenderPayload(result(), [clip()], initialStudioState, {});
    const missing = BACKEND_SETTINGS_FIELDS.filter((f) => !(f in payload.settings));
    expect(missing).toEqual([]);
  });

  it('sends no field the backend does not know', () => {
    const payload = buildRenderPayload(result(), [clip()], initialStudioState, {});
    const extra = Object.keys(payload.settings).filter(
      (k) => !BACKEND_SETTINGS_FIELDS.includes(k as (typeof BACKEND_SETTINGS_FIELDS)[number]),
    );
    expect(extra).toEqual([]);
  });

  it('uses snake_case throughout', () => {
    const payload = buildRenderPayload(result(), [clip()], initialStudioState, {});
    for (const key of Object.keys(payload.settings)) {
      expect(key, `${key} is not snake_case`).toMatch(/^[a-z][a-z0-9_]*$/);
    }
  });
});

describe('transcript placement', () => {
  it('sits at the top level, beside settings', () => {
    // Nested inside settings it would be ignored, and the backend would
    // silently re-transcribe every clip with Whisper.
    const payload = buildRenderPayload(result(), [clip()], initialStudioState, {});
    expect(payload.transcript).toBeDefined();
    expect(payload.settings).not.toHaveProperty('transcript');
  });

  it('passes the transcript through unchanged', () => {
    const r = result();
    expect(buildRenderPayload(r, [clip()], initialStudioState, {}).transcript).toEqual(r.transcript);
  });

  it('survives a video with no transcript', () => {
    const payload = buildRenderPayload(
      result({ transcript: undefined }),
      [clip()],
      initialStudioState,
      {},
    );
    expect(payload.transcript).toBeUndefined();
  });
});

describe('clips', () => {
  it('carries custom_title on each clip', () => {
    const payload = buildRenderPayload(result(), [clip()], initialStudioState, {
      'clip-1': 'Judul pilihan saya',
    });
    expect(payload.clips[0].custom_title).toBe('Judul pilihan saya');
  });

  it('falls back to the suggestion, matching backend precedence', () => {
    const c = clip({ title_suggestion: 'Saran AI' });
    const payload = buildRenderPayload(result(), [c], initialStudioState, {});
    expect(payload.clips[0].custom_title).toBe('Saran AI');
  });

  it('keeps the clip timings', () => {
    const payload = buildRenderPayload(result(), [clip()], initialStudioState, {});
    expect(payload.clips[0].start_time).toBe(10);
    expect(payload.clips[0].end_time).toBe(40);
  });

  it('sends only the selected clips', () => {
    const a = clip({ id: 'a' });
    const b = clip({ id: 'b' });
    const payload = buildRenderPayload(result({ clips: [a, b] }), [b], initialStudioState, {});
    expect(payload.clips).toHaveLength(1);
    expect(payload.clips[0].id).toBe('b');
  });
});

describe('top-level keys', () => {
  it('names the video by its ID only; the backend builds the URL (#70)', () => {
    const payload = buildRenderPayload(result(), [clip()], initialStudioState, {});
    expect(payload.video_id).toBe('abc12345678');
    expect('video_url' in payload).toBe(false);
  });

  it('has exactly the four keys the backend reads', () => {
    const payload = buildRenderPayload(result(), [clip()], initialStudioState, {});
    expect(Object.keys(payload).sort()).toEqual(['clips', 'settings', 'transcript', 'video_id'].sort());
  });
});

describe('audio toggles', () => {
  it('stays off when enabled but no file was uploaded', () => {
    const payload = buildRenderPayload(
      result(),
      [clip()],
      { ...initialStudioState, bgmEnabled: true, bgmFilePath: null },
      {},
    );
    expect(payload.settings.bgm_enabled).toBe(false);
  });

  it('turns on once a file is present', () => {
    const payload = buildRenderPayload(
      result(),
      [clip()],
      { ...initialStudioState, bgmEnabled: true, bgmFilePath: '/tmp/a.mp3' },
      {},
    );
    expect(payload.settings.bgm_enabled).toBe(true);
  });

  it('applies the same rule to the hook sound effect', () => {
    const payload = buildRenderPayload(
      result(),
      [clip()],
      { ...initialStudioState, hookSfxEnabled: true, hookSfxFilePath: null },
      {},
    );
    expect(payload.settings.hook_sfx_enabled).toBe(false);
  });
});

describe('outputFileName', () => {
  it('adds the prefix and suffix', () => {
    expect(outputFileName('Judul', 'EP1 - ', ' [HD]', new Map())).toBe('EP1 - Judul [HD].mp4');
  });

  it('strips characters Windows rejects', () => {
    expect(outputFileName('a/b:c*d?e"f<g>h|i', '', '', new Map())).toBe('abcdefghi.mp4');
  });

  it('numbers duplicates instead of overwriting', () => {
    const seen = new Map<string, number>();
    expect(outputFileName('Sama', '', '', seen)).toBe('Sama.mp4');
    expect(outputFileName('Sama', '', '', seen)).toBe('Sama (1).mp4');
    expect(outputFileName('Sama', '', '', seen)).toBe('Sama (2).mp4');
  });

  it('keeps different titles apart', () => {
    const seen = new Map<string, number>();
    expect(outputFileName('Satu', '', '', seen)).toBe('Satu.mp4');
    expect(outputFileName('Dua', '', '', seen)).toBe('Dua.mp4');
  });

  it('falls back when the title sanitises to nothing', () => {
    expect(outputFileName('///', '', '', new Map())).toBe('clip.mp4');
  });
});
