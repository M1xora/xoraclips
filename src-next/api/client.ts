/**
 * Centralised API client.
 *
 * Replaces the 18 inline fetch() call sites of the previous frontend.
 * Every backend call goes through here so that error handling, status
 * checking and payload shapes live in exactly one place.
 */

/** Error carrying the HTTP status, the backend's message and, when given, an error code. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  /** e.g. `key_invalid`, `key_quota` (backend ai_errors.py). */
  readonly code?: string;

  constructor(status: number, detail: string, code?: string) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.code = code;
  }
}

/** The request header that carries the user's Gemini key (issue #12). */
export const GEMINI_KEY_HEADER = 'X-Gemini-Api-Key';

/** Headers for a request that uses the user's key; none when there is no key. */
export function geminiKeyHeaders(apiKey?: string): Record<string, string> {
  const key = apiKey?.trim();
  return key ? { [GEMINI_KEY_HEADER]: key } : {};
}

/**
 * Reads the backend's error body and turns it into an ApiError.
 * FastAPI reports problems as `{ "detail": "..." }`, as
 * `{ "detail": { "code": "...", "message": "..." } }` for coded errors, or
 * as a list of `{ "msg": "..." }` when a request fails validation (422).
 */
async function toApiError(res: Response): Promise<ApiError> {
  let detail = `Request failed with status ${res.status}`;
  let code: string | undefined;
  try {
    const body = await res.json();
    if (body && typeof body.detail === 'string') detail = body.detail;
    else if (body?.detail && typeof body.detail === 'object') {
      if (typeof body.detail.message === 'string') detail = body.detail.message;
      if (typeof body.detail.code === 'string') code = body.detail.code;
      if (Array.isArray(body.detail) && typeof body.detail[0]?.msg === 'string') {
        detail = body.detail[0].msg.replace(/^Value error, /, '');
      }
    }
  } catch {
    // Body was not JSON - keep the status-based message.
  }
  return new ApiError(res.status, detail, code);
}

/**
 * fetch() wrapper that always checks `res.ok`.
 *
 * The old frontend skipped this check on /api/analyze, so backend errors
 * surfaced to users as a misleading "connection closed" message.
 */
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) throw await toApiError(res);
  return res.json() as Promise<T>;
}

/** Largest uploads the backend accepts (backend/uploads.py, #58): checked
 *  here too, so a big file fails at once instead of after the upload. */
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;
export const MAX_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024;

export class UploadTooLargeError extends Error {
  readonly size: number;

  constructor(size: number, max: number = MAX_UPLOAD_BYTES) {
    super(
      `File terlalu besar (${(size / 1024 / 1024).toFixed(1)} MB). ` +
        `Maksimum ${max / 1024 / 1024} MB.`,
    );
    this.name = 'UploadTooLargeError';
    this.size = size;
  }
}

/** POST a JSON body and parse a JSON response. */
function postJson<T>(url: string, body: unknown, signal?: AbortSignal): Promise<T> {
  return request<T>(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
}

/** POST a single file as multipart/form-data, rejecting oversized files. */
function postFile<T>(url: string, file: File, signal: AbortSignal | undefined, maxBytes: number): Promise<T> {
  if (file.size > maxBytes) {
    return Promise.reject(new UploadTooLargeError(file.size, maxBytes));
  }
  const form = new FormData();
  form.append('file', file);
  return request<T>(url, { method: 'POST', body: form, signal });
}

// ---------------------------------------------------------------------------
// Response shapes
// ---------------------------------------------------------------------------

export interface CookieStatus {
  exists: boolean;
  has_cookies: boolean;
  size: number;
  /** Cookie domains. The backend never sends the cookies themselves (#45). */
  sample_lines: string[];
}

export interface UploadResult {
  success: boolean;
  filename: string;
  saved_name: string;
  file_path: string;
  url: string;
  size_bytes: number;
}

export interface RawJobStart {
  job_id: string;
  status: string;
}

export interface RawJobStatus {
  job_id: string;
  status: 'starting' | 'downloading' | 'ready' | 'failed';
  progress_percent: number;
  /**
   * Only the full-video job reports these (main.py:2795-2798). The clip job
   * omits them entirely, so they are optional rather than empty strings.
   */
  downloaded?: string;
  total?: string;
  speed?: string;
  eta?: string;
  download_url: string | null;
  filename: string;
  error: string | null;
}

/** One highlighted word inside a caption chunk. Times relative to clip start. */
export interface ApiCaptionWord {
  text: string;
  start: number;
  end: number;
}

/** A caption exactly as the export burns it (backend captions.py). */
export interface ApiCaptionChunk {
  start: number;
  end: number;
  text: string;
  words: ApiCaptionWord[];
}

export interface CaptionChunksRequest {
  transcript: import('../lib/types').TranscriptLine[];
  clip_start: number;
  clip_end: number;
  text_case: import('../lib/types').TextCaseOption;
}

export interface CaptionChunksResponse {
  chunks: ApiCaptionChunk[];
  /** `none`: no transcript, so the render will fall back to Whisper. */
  source: 'transcript' | 'none';
}

export interface FaceBox {
  found: boolean;
  cx: number;
  cy: number;
  w: number;
  h: number;
  frame_url: string;
}

export interface TempStorageInfo {
  total_files: number;
  total_bytes: number;
  total_mb: number;
  formatted_size: string;
}

export interface BatchStart {
  batch_id: string;
  total_clips: number;
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

export const api = {
  /**
   * Gemini models available to the user's key, sent only in the header.
   * Also a key check: a key Google rejects throws ApiError with code
   * `key_invalid` (or `key_quota`).
   */
  listModels: (apiKey?: string, signal?: AbortSignal) =>
    request<{ models: string[] }>('/api/models', { signal, headers: geminiKeyHeaders(apiKey) }),

  /** Server configuration, e.g. whether mock mode is on. */
  health: (signal?: AbortSignal) =>
    request<import('../features/analyze/serverStatus').HealthInfo>('/api/health', { signal }),

  hardwareAccel: (signal?: AbortSignal) =>
    request<import('../lib/types').HardwareAccelInfo>('/api/hardware-accel', { signal }),

  /** The backend takes only the video ID and builds the YouTube URL itself (#42). */
  detectFace: (videoId: string, timestamp: number, signal?: AbortSignal) => {
    const params = new URLSearchParams({ video_id: videoId, timestamp: String(timestamp) });
    return request<FaceBox>(`/api/detect-face?${params}`, { signal });
  },

  /** Caption chunks for a clip, computed by the same code as the render. */
  captionChunks: (body: CaptionChunksRequest, signal?: AbortSignal) =>
    postJson<CaptionChunksResponse>('/api/caption-chunks', body, signal),

  clipFrameUrl: (videoId: string, timestamp: number) =>
    `/api/clip-frame?video_id=${encodeURIComponent(videoId)}&timestamp=${timestamp}`,

  cookies: {
    status: () => request<CookieStatus>('/api/cookies'),
    save: (content: string) =>
      postJson<{ success: boolean; size: number }>('/api/cookies', { cookies_content: content }),
    remove: () => request<{ success: boolean }>('/api/cookies', { method: 'DELETE' }),
  },

  uploads: {
    bgm: (file: File, signal?: AbortSignal) =>
      postFile<UploadResult>('/api/upload-bgm', file, signal, MAX_UPLOAD_BYTES),
    sfx: (file: File, signal?: AbortSignal) =>
      postFile<UploadResult>('/api/upload-sfx', file, signal, MAX_UPLOAD_BYTES),
    watermark: (file: File, signal?: AbortSignal) =>
      postFile<UploadResult>('/api/upload-watermark', file, signal, MAX_IMAGE_UPLOAD_BYTES),
  },

  render: {
    startBatch: (payload: unknown, signal?: AbortSignal) =>
      postJson<BatchStart>('/api/render-batch', payload, signal),
    /** Server-sent events stream of batch progress. Caller must close it. */
    progressStream: (batchId: string) =>
      new EventSource(`/api/render-progress/${encodeURIComponent(batchId)}`),
  },

  rawDownload: {
    startVideo: (payload: { video_id: string; title?: string }) =>
      postJson<RawJobStart>('/api/download-raw-video', payload),
    videoStatus: (jobId: string) =>
      request<RawJobStatus>(`/api/download-raw-status/${encodeURIComponent(jobId)}`),
    startClip: (payload: {
      video_id: string;
      start_time: number;
      end_time: number;
      title: string;
    }) => postJson<RawJobStart>('/api/download-raw-clip', payload),
    clipStatus: (jobId: string) =>
      request<RawJobStatus>(`/api/download-raw-clip-status/${encodeURIComponent(jobId)}`),
  },

  temp: {
    info: () => request<TempStorageInfo>('/api/temp-storage-info'),
    clear: () => request<{ success: boolean; cleared_files: number }>('/api/clear-temp', {
      method: 'POST',
    }),
  },
};
