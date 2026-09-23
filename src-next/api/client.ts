/**
 * Centralised API client.
 *
 * Replaces the 18 inline fetch() call sites of the previous frontend.
 * Every backend call goes through here so that error handling, status
 * checking and payload shapes live in exactly one place.
 */

/** Error carrying the HTTP status and the backend's `detail` message. */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

/**
 * Reads the backend's error body and turns it into an ApiError.
 * FastAPI reports problems as `{ "detail": "..." }`.
 */
async function toApiError(res: Response): Promise<ApiError> {
  let detail = `Request failed with status ${res.status}`;
  try {
    const body = await res.json();
    if (body && typeof body.detail === 'string') detail = body.detail;
  } catch {
    // Body was not JSON - keep the status-based message.
  }
  return new ApiError(res.status, detail);
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

/** Largest upload accepted. The backend reads the whole body into memory
 *  (main.py:2619) with no cap of its own, so the check happens here. */
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;

export class UploadTooLargeError extends Error {
  readonly size: number;

  constructor(size: number) {
    super(
      `File terlalu besar (${(size / 1024 / 1024).toFixed(1)} MB). ` +
        `Maksimum ${MAX_UPLOAD_BYTES / 1024 / 1024} MB.`,
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
function postFile<T>(url: string, file: File, signal?: AbortSignal): Promise<T> {
  if (file.size > MAX_UPLOAD_BYTES) {
    return Promise.reject(new UploadTooLargeError(file.size));
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
  sample_lines: string[];
  cookies_content: string;
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
   * Available Gemini models for a key.
   *
   * NOTE: the backend declares this as GET /api/models?api_key=... so the key
   * travels in the query string, where it lands in browser history and server
   * access logs. Changing that needs a backend edit (accept a POST body), which
   * is out of scope for the frontend rewrite. Isolated here so there is exactly
   * one place to fix once the backend accepts a body.
   */
  listModels: (apiKey: string, signal?: AbortSignal) =>
    request<{ models: string[] }>(`/api/models?api_key=${encodeURIComponent(apiKey)}`, { signal }),

  hardwareAccel: (signal?: AbortSignal) =>
    request<import('../lib/types').HardwareAccelInfo>('/api/hardware-accel', { signal }),

  detectFace: (
    videoId: string,
    timestamp: number,
    videoUrl?: string,
    signal?: AbortSignal,
  ) => {
    const params = new URLSearchParams({ video_id: videoId, timestamp: String(timestamp) });
    if (videoUrl) params.set('video_url', videoUrl);
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
    bgm: (file: File, signal?: AbortSignal) => postFile<UploadResult>('/api/upload-bgm', file, signal),
    sfx: (file: File, signal?: AbortSignal) => postFile<UploadResult>('/api/upload-sfx', file, signal),
    watermark: (file: File, signal?: AbortSignal) =>
      postFile<UploadResult>('/api/upload-watermark', file, signal),
  },

  render: {
    startBatch: (payload: unknown, signal?: AbortSignal) =>
      postJson<BatchStart>('/api/render-batch', payload, signal),
    /** Server-sent events stream of batch progress. Caller must close it. */
    progressStream: (batchId: string) =>
      new EventSource(`/api/render-progress/${encodeURIComponent(batchId)}`),
  },

  rawDownload: {
    startVideo: (payload: { video_url: string; video_id: string; title?: string }) =>
      postJson<RawJobStart>('/api/download-raw-video', payload),
    videoStatus: (jobId: string) =>
      request<RawJobStatus>(`/api/download-raw-status/${encodeURIComponent(jobId)}`),
    startClip: (payload: {
      video_url: string;
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
