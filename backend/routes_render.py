"""
Batch rendering: the render settings, the background job that downloads,
captions and renders each clip, its progress stream and ZIP, the caption
chunks the preview shows, and the hardware encoder options. The video is
named by its checked YouTube ID; batches are forgotten an hour after they
finish (#70).
"""
import asyncio
import json
import logging
import os
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

try:
    from backend import video_engine
    from backend.captions import caption_chunks_for_clip
    from backend.job_store import JobStore, new_job_id
    from backend.uploads import MissingUpload, resolve_upload
    from backend.validation import VIDEO_SECONDS, check_time_range, clean_file_title, require_video_id
    from backend.video_engine import (
        ACTIVE_ENCODER_NAME, detect_hardware_support,
        download_clip_segment, generate_ass_file, has_emoji, render_clip_to_mp4,
        render_title_overlay_png, transcribe_clip_words, watch_url,
    )
except ImportError:
    import video_engine
    from captions import caption_chunks_for_clip
    from job_store import JobStore, new_job_id
    from uploads import MissingUpload, resolve_upload
    from validation import VIDEO_SECONDS, check_time_range, clean_file_title, require_video_id
    from video_engine import (
        ACTIVE_ENCODER_NAME, detect_hardware_support,
        download_clip_segment, generate_ass_file, has_emoji, render_clip_to_mp4,
        render_title_overlay_png, transcribe_clip_words, watch_url,
    )

logger = logging.getLogger("xoraclips")
router = APIRouter()


class RenderSettingsModel(BaseModel):
    aspect_ratio: str = "9:16"
    background_style: str = "black"
    enable_face_tracking: bool = True
    streamer_preset: str = "none"
    title_text: Optional[str] = None
    title_prefix: Optional[str] = ""
    title_suffix: Optional[str] = ""
    file_name_prefix: Optional[str] = ""
    file_name_suffix: Optional[str] = ""
    title_position: str = "auto"
    title_duration: Optional[str] = "entire"
    subtitles_enabled: Optional[bool] = True
    caption_style: str = "viral_pop"
    caption_font: str = "Outfit"
    font_size: str = "medium"
    title_font_size: Optional[str] = "medium"
    text_case: str = "uppercase"
    title_y_percent: Optional[float] = 14.0
    subtitle_y_percent: Optional[float] = 18.0
    subtitle_position_mode: Optional[str] = "bottom"
    subtitle_center_y_percent: Optional[float] = 50.0
    # Background Music
    bgm_enabled: Optional[bool] = False
    bgm_file_path: Optional[str] = None
    bgm_volume: Optional[float] = 25.0
    bgm_start_offset: Optional[float] = 0.0
    # Hook SFX
    hook_sfx_enabled: Optional[bool] = False
    hook_sfx_file_path: Optional[str] = None
    hook_sfx_volume: Optional[float] = 100.0
    # Raw Audio / Voice Boost
    original_audio_volume: Optional[float] = 100.0
    # Watermark
    watermark_enabled: Optional[bool] = False
    watermark_type: Optional[str] = "image"
    watermark_file_path: Optional[str] = None
    watermark_text: Optional[str] = None
    watermark_size: Optional[float] = 20.0
    watermark_opacity: Optional[float] = 80.0
    watermark_x: Optional[float] = 90.0
    watermark_y: Optional[float] = 8.0
    hardware_accel: Optional[str] = "auto"


MAX_CLIPS_PER_BATCH = 50


class RenderClip(BaseModel):
    """One clip to render: the analysis fields the app sends are kept as they
    are; the ones the render reads are checked (#70)."""
    model_config = ConfigDict(extra="allow")

    start_time: float = VIDEO_SECONDS
    end_time: float = VIDEO_SECONDS
    title: Optional[str] = None
    title_suggestion: Optional[str] = None
    custom_title: Optional[str] = None

    @model_validator(mode="after")
    def _end_after_start(self):
        check_time_range(self.start_time, self.end_time)
        return self


class RenderBatchRequest(BaseModel):
    video_id: str
    video_url: Optional[str] = None   # still sent by the app; ignored (#70)
    clips: List[RenderClip] = Field(max_length=MAX_CLIPS_PER_BATCH)
    settings: RenderSettingsModel
    transcript: Optional[List[Dict[str, Any]]] = None


RENDER_BATCHES = JobStore()


def clip_titles(clip: RenderClip, idx: int, settings: RenderSettingsModel, clip_count: int) -> Tuple[str, Optional[str]]:
    """The clip's own title, and the title drawn on the video (None when
    titles are off). Used when the batch starts and when the clip renders,
    so the queue never changes a title half way (#70)."""
    base_title = (clip.custom_title or clip.title_suggestion or clip.title or f"Clip {idx + 1}").strip()
    if settings.title_position == "none":
        return base_title, None
    prefix, suffix = settings.title_prefix or "", settings.title_suffix or ""
    if prefix or suffix:
        return base_title, f"{prefix}{base_title}{suffix}".strip()
    if clip_count == 1 and (settings.title_text or "").strip() and not (clip.custom_title or clip.title_suggestion):
        return base_title, settings.title_text.strip()
    return base_title, base_title


def file_title(base_title: str, clip_index: int, settings: RenderSettingsModel) -> str:
    """A clip's name inside the ZIP (without .mp4): its own title with the
    file name prefix and suffix, never the on-screen affixes."""
    clean = clean_file_title(base_title) or f"clip_{clip_index}"
    named = f"{clean_file_title(settings.file_name_prefix)}{clean}{clean_file_title(settings.file_name_suffix)}"
    return named.strip() or clean


def zip_path(batch_id: str) -> Path:
    return video_engine.EXPORTS_DIR / f"xoraclips_{os.path.basename(batch_id)}.zip"


def build_batch_zip(batch: Dict[str, Any]) -> Optional[Path]:
    """The ZIP of a batch's finished clips, or None when there are none.
    Stored without compression (MP4 does not shrink) and written to a
    temporary name first, so a failed write never leaves a broken ZIP that
    would be served from then on. Runs in a thread: it can take a while."""
    finished = []
    for clip in batch["clips"]:
        path = clip.get("output_path")
        if clip.get("status") == "completed" and path and os.path.exists(path):
            finished.append((path, clip.get("file_title") or os.path.splitext(os.path.basename(path))[0]))
    if not finished:
        return None
    target = zip_path(batch["batch_id"])
    partial = target.with_name(f"{target.name}.{uuid.uuid4().hex[:8]}.part")
    seen: Dict[str, int] = {}
    try:
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_STORED) as archive:
            for path, name in finished:
                count = seen.get(name, 0)
                seen[name] = count + 1
                archive.write(path, arcname=f"{name}.mp4" if count == 0 else f"{name} ({count}).mp4")
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return target


async def process_batch_rendering(batch_id: str, request: RenderBatchRequest):
    batch = RENDER_BATCHES.get(batch_id)
    if not batch:
        return

    clips = request.clips
    settings = request.settings
    # Uploaded files by their saved name, never a path from the request (#58).
    # One that is gone fails the batch: a render without the music or logo
    # the user chose would look finished but be wrong.
    try:
        image_watermark = settings.watermark_enabled and (settings.watermark_type or "image") == "image"
        watermark_path = resolve_upload(settings.watermark_file_path, "watermark") if image_watermark else None
        bgm_path = resolve_upload(settings.bgm_file_path, "bgm") if settings.bgm_enabled else None
        hook_sfx_path = resolve_upload(settings.hook_sfx_file_path, "sfx") if settings.hook_sfx_enabled else None
    except MissingUpload as e:
        for clip_status in batch["clips"]:
            clip_status.update(status="error", error=str(e), error_message=str(e))
        batch["overall_status"] = "error"
        batch["error_message"] = str(e)
        RENDER_BATCHES.finish(batch_id)
        return

    try:
        await _render_clips(batch_id, batch, request, watermark_path, bgm_path, hook_sfx_path)
    finally:
        RENDER_BATCHES.finish(batch_id)


async def _render_clips(batch_id: str, batch: Dict[str, Any], request: RenderBatchRequest,
                        watermark_path: Optional[str], bgm_path: Optional[str], hook_sfx_path: Optional[str]):
    clips = request.clips
    settings = request.settings
    target_url = watch_url(request.video_id)   # checked when the batch started

    for idx, clip in enumerate(clips):
        clip_status = batch["clips"][idx]
        clip_status["status"] = "downloading"
        clip_status["progress_percent"] = 15

        try:
            # 1. Download
            start_t = clip.start_time
            end_t = clip.end_time
            seg_filename = f"{batch_id}_clip_{idx}_raw.mp4"

            # Retries and method changes show on screen while downloading (#10).
            def download_status(event, clip_status=clip_status):
                clip_status["download_note"] = event

            raw_path = await asyncio.to_thread(
                download_clip_segment,
                target_url,
                start_t,
                end_t,
                seg_filename,
                download_status,
            )
            clip_status.pop("download_note", None)

            # 2. Transcribe & Generate Subtitles / Title (.ass)
            clip_status["status"] = "transcribing"
            clip_status["progress_percent"] = 40

            base_title, display_title = clip_titles(clip, idx, settings, len(clips))

            ass_path = None
            title_overlay_path = None
            skip_ass_title = False
            duration_sec = max(1.0, end_t - start_t)

            # Check if title has emoji -> render transparent color emoji PNG overlay
            if display_title and settings.title_position != "none" and has_emoji(display_title):
                title_png_filename = f"{batch_id}_clip_{idx}_title.png"
                title_png_path = str(video_engine.TEMP_DIR / title_png_filename)
                try:
                    rendered_overlay = await asyncio.to_thread(
                        render_title_overlay_png,
                        title_text=display_title,
                        output_png_path=title_png_path,
                        font_name=settings.caption_font or "Montserrat",
                        target_aspect_ratio=settings.aspect_ratio or "9:16",
                        font_size_preset=settings.font_size or "medium",
                        text_case=settings.text_case or "uppercase",
                        title_position=settings.title_position or "auto",
                        title_y_percent=settings.title_y_percent if settings.title_y_percent is not None else 14.0,
                        title_font_size_preset=settings.title_font_size or settings.font_size or "medium"
                    )
                    if rendered_overlay and os.path.exists(rendered_overlay):
                        title_overlay_path = rendered_overlay
                        skip_ass_title = True
                        logger.info(f"Rendered full-color emoji title overlay: {title_overlay_path}")
                except Exception as ex:
                    logger.warning(f"Could not render color emoji title overlay: {ex}")
                    skip_ass_title = False

            if settings.caption_style != "none" or (display_title and settings.title_position != "none" and not skip_ass_title):
                words = []
                if settings.caption_style != "none":
                    words = await asyncio.to_thread(
                        transcribe_clip_words,
                        raw_path,
                        request.transcript,
                        start_t,
                        end_t
                    )
                ass_filename = f"{batch_id}_clip_{idx}.ass"
                ass_path = str(video_engine.TEMP_DIR / ass_filename)
                await asyncio.to_thread(
                    generate_ass_file,
                    words=words,
                    style_preset=settings.caption_style,
                    font_name=settings.caption_font,
                    output_ass_path=ass_path,
                    target_aspect_ratio=settings.aspect_ratio,
                    font_size_preset=settings.font_size,
                    text_case=settings.text_case,
                    title_text=display_title if not skip_ass_title else None,
                    title_position=settings.title_position,
                    title_duration=settings.title_duration if settings.title_duration else "entire",
                    duration_seconds=duration_sec,
                    title_y_percent=settings.title_y_percent if settings.title_y_percent is not None else 14.0,
                    subtitle_y_percent=settings.subtitle_y_percent if settings.subtitle_y_percent is not None else 18.0,
                    subtitle_position_mode=settings.subtitle_position_mode if settings.subtitle_position_mode else "bottom",
                    subtitle_center_y_percent=settings.subtitle_center_y_percent if settings.subtitle_center_y_percent is not None else 50.0,
                    skip_title=skip_ass_title,
                    title_font_size_preset=settings.title_font_size or settings.font_size or "medium"
                )

            # 3. Render Final Vertical MP4
            clip_status["status"] = "rendering"
            clip_status["progress_percent"] = 70

            out_filename = f"clip_{idx+1}_{batch_id}.mp4"
            out_path = str(video_engine.EXPORTS_DIR / out_filename)

            await asyncio.to_thread(
                render_clip_to_mp4,
                video_path=raw_path,
                output_mp4_path=out_path,
                aspect_ratio=settings.aspect_ratio,
                background_style=settings.background_style,
                enable_face_tracking=settings.enable_face_tracking,
                streamer_preset=settings.streamer_preset,
                title_text=display_title if not skip_ass_title else None,
                title_position=settings.title_position,
                ass_subtitles_path=ass_path,
                clip_duration=duration_sec,
                title_overlay_path=title_overlay_path,
                title_duration=settings.title_duration if settings.title_duration else "entire",
                watermark_enabled=bool(settings.watermark_enabled),
                watermark_type=settings.watermark_type or "image",
                watermark_image_path=watermark_path,
                watermark_text=settings.watermark_text,
                watermark_size=float(settings.watermark_size if settings.watermark_size is not None else 20.0),
                watermark_opacity=float((settings.watermark_opacity if settings.watermark_opacity is not None else 80.0) / 100.0),
                watermark_x_percent=float(settings.watermark_x if settings.watermark_x is not None else 90.0),
                watermark_y_percent=float(settings.watermark_y if settings.watermark_y is not None else 8.0),
                bgm_enabled=bool(settings.bgm_enabled),
                bgm_path=bgm_path,
                bgm_volume=float((settings.bgm_volume if settings.bgm_volume is not None else 25.0) / 100.0),
                bgm_start_offset=float(settings.bgm_start_offset or 0.0),
                hook_sfx_enabled=bool(settings.hook_sfx_enabled),
                hook_sfx_path=hook_sfx_path,
                hook_sfx_volume=float((settings.hook_sfx_volume if settings.hook_sfx_volume is not None else 100.0) / 100.0),
                original_audio_volume=float((settings.original_audio_volume if settings.original_audio_volume is not None else 100.0) / 100.0),
                hardware_accel=settings.hardware_accel or "auto"
            )

            clip_status["status"] = "completed"
            clip_status["progress_percent"] = 100
            clip_status["download_url"] = f"/api/download-rendered/{out_filename}"
            clip_status["output_path"] = out_path
            clip_status["file_title"] = file_title(base_title, idx + 1, settings)

        except Exception as e:
            logger.error(f"Error rendering clip {idx} in batch {batch_id}: {e}")
            clip_status["status"] = "error"
            clip_status["error_message"] = str(e)
            clip_status["error"] = str(e)
            clip_status.pop("download_note", None)

        batch["current_clip_index"] = idx + 1

    try:
        batch["zip_url"] = f"/api/download-batch-zip/{batch_id}" if await asyncio.to_thread(build_batch_zip, batch) else None
    except Exception as e:
        logger.warning(f"Failed to create batch zip: {e}")

    # Determine overall status and error messaging
    failed_clips = [c for c in batch["clips"] if c.get("status") == "error"]

    if len(failed_clips) == len(batch["clips"]):
        batch["overall_status"] = "error"
        batch["error_message"] = f"All {len(batch['clips'])} clip(s) failed to render. Please review the error details."
    elif len(failed_clips) > 0:
        batch["overall_status"] = "completed"
        batch["warning_message"] = f"{len(failed_clips)} of {len(batch['clips'])} clips encountered errors."
    else:
        batch["overall_status"] = "completed"


class CaptionChunksRequest(BaseModel):
    transcript: List[Dict[str, Any]] = Field(default_factory=list)
    clip_start: float
    clip_end: float
    text_case: str = "uppercase"


@router.post("/api/caption-chunks")
def get_caption_chunks(request: CaptionChunksRequest):
    """
    The caption chunks a clip's export will burn in, for the browser preview.
    Uses the same function as generate_ass_file(), so preview == render.
    Times are relative to clip_start. Empty when the transcript has no words
    in this clip (or there is no transcript): the render then falls back to
    Whisper, which the preview cannot match.
    """
    chunks = caption_chunks_for_clip(
        request.transcript, request.clip_start, request.clip_end, request.text_case
    )
    return {"chunks": chunks, "source": "transcript" if chunks else "none"}


@router.post("/api/render-batch")
async def start_batch_render(request: RenderBatchRequest, background_tasks: BackgroundTasks):
    if not request.clips:
        raise HTTPException(status_code=400, detail="No clips provided for rendering")
    require_video_id(request.video_id)

    # Unguessable: the rendered files are downloaded by names that contain it.
    batch_id = f"batch_{new_job_id()}"

    clips_status = []
    for idx, clip in enumerate(request.clips):
        base_title, display_title = clip_titles(clip, idx, request.settings, len(request.clips))
        clips_status.append({
            "clip_index": idx,
            "title": display_title or base_title,
            "base_title": base_title,
            "status": "pending",
            "progress_percent": 0
        })

    RENDER_BATCHES.add(batch_id, {
        "batch_id": batch_id,
        "total_clips": len(request.clips),
        "current_clip_index": 0,
        "overall_status": "running",
        "clips": clips_status,
        "zip_url": None
    })

    background_tasks.add_task(process_batch_rendering, batch_id, request)
    return {"batch_id": batch_id, "total_clips": len(request.clips)}


@router.get("/api/render-progress/{batch_id}")
async def get_render_progress(batch_id: str):
    if RENDER_BATCHES.lookup(batch_id) is None:
        raise HTTPException(status_code=404, detail="Batch not found")

    async def stream():
        while True:
            batch = RENDER_BATCHES.get(batch_id)
            if not batch:
                break
            yield f"data: {json.dumps(batch)}\n\n"
            if batch.get("overall_status") in ["completed", "error"]:
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@router.get("/api/download-batch-zip/{batch_id}")
def download_batch_zip(batch_id: str):
    """The batch's ZIP; made now from the clips finished so far when it does
    not exist yet. 404 when no clip has finished."""
    path = zip_path(batch_id)
    if not path.exists():
        batch = RENDER_BATCHES.lookup(batch_id)
        try:
            path = build_batch_zip(batch) if batch else None
        except Exception as e:
            logger.error(f"Error packaging batch zip on the fly: {e}")
            path = None
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="Batch zip file not found")
    return FileResponse(path, media_type="application/zip", filename=path.name)


@router.get("/api/hardware-accel")
def get_hardware_acceleration_status():
    """Returns detected GPU/CPU hardware acceleration options and recommendations."""
    support = detect_hardware_support()
    rec = support.get("recommended", "cpu")
    return {
        "status": "success",
        "active_default": ACTIVE_ENCODER_NAME,
        "recommended": rec,
        "support": support,
        "options": [
            {
                "id": "auto",
                "label": "Auto Detect",
                "sub": f"Recommended ({rec.upper()})",
                "available": True,
            },
            {
                "id": "nvenc",
                "label": "NVIDIA NVENC",
                "sub": "GeForce & RTX Hardware Acceleration",
                "available": support.get("nvenc", False),
            },
            {
                "id": "amf",
                "label": "AMD AMF",
                "sub": "Radeon RX & APU Hardware Acceleration",
                "available": support.get("amf", False),
            },
            {
                "id": "qsv",
                "label": "Intel QuickSync",
                "sub": "Intel Arc & UHD Hardware Acceleration",
                "available": support.get("qsv", False),
            },
            {
                "id": "cpu",
                "label": "CPU Software (libx264)",
                "sub": "Multi-threaded CPU (100% Universal)",
                "available": True,
            },
        ],
    }
