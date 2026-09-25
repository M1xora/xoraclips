"""
Batch rendering: the render settings, the background job that downloads,
captions and renders each clip, its progress stream and ZIP, the caption
chunks the preview shows, and the hardware encoder options. Moved out of
main.py unchanged (#60).
"""
import asyncio
import json
import logging
import os
import re
import time
import uuid
import zipfile
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

try:
    from backend import video_engine
    from backend.captions import caption_chunks_for_clip
    from backend.uploads import resolve_upload
    from backend.video_engine import (
        ACTIVE_ENCODER_NAME, detect_hardware_support,
        download_clip_segment, generate_ass_file, has_emoji, render_clip_to_mp4,
        render_title_overlay_png, transcribe_clip_words,
    )
except ImportError:
    import video_engine
    from captions import caption_chunks_for_clip
    from uploads import resolve_upload
    from video_engine import (
        ACTIVE_ENCODER_NAME, detect_hardware_support,
        download_clip_segment, generate_ass_file, has_emoji, render_clip_to_mp4,
        render_title_overlay_png, transcribe_clip_words,
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


class RenderBatchRequest(BaseModel):
    video_url: str
    video_id: str
    clips: List[Dict[str, Any]]
    settings: RenderSettingsModel
    transcript: Optional[List[Dict[str, Any]]] = None


RENDER_BATCHES: Dict[str, Dict[str, Any]] = {}


async def process_batch_rendering(batch_id: str, request: RenderBatchRequest):
    batch = RENDER_BATCHES.get(batch_id)
    if not batch:
        return

    clips = request.clips
    settings = request.settings
    # Uploaded files by their saved name, never a path from the request (#58).
    watermark_path = resolve_upload(settings.watermark_file_path, "watermark") if settings.watermark_enabled else None
    bgm_path = resolve_upload(settings.bgm_file_path, "bgm") if settings.bgm_enabled else None
    hook_sfx_path = resolve_upload(settings.hook_sfx_file_path, "sfx") if settings.hook_sfx_enabled else None

    # Normalize video URL for history or direct URL
    target_url = (request.video_url or "").strip()
    if not target_url.startswith("http"):
        target_url = f"https://www.youtube.com/watch?v={request.video_id or target_url}"

    for idx, clip in enumerate(clips):
        clip_status = batch["clips"][idx]
        clip_status["status"] = "downloading"
        clip_status["progress_percent"] = 15

        try:
            # 1. Download
            start_t = float(clip.get("start_time", 0.0))
            end_t = float(clip.get("end_time", start_t + 30.0))
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

            display_title = None
            base_title = (
                clip.get("custom_title")
                or clip.get("title_suggestion")
                or clip.get("title")
                or f"Clip {idx+1}"
            ).strip()

            if settings.title_position != "none":
                pfx = settings.title_prefix or ""
                sfx = settings.title_suffix or ""
                if pfx or sfx:
                    display_title = f"{pfx}{base_title}{sfx}".strip()
                elif len(clips) == 1 and settings.title_text and settings.title_text.strip() and not (clip.get("custom_title") or clip.get("title_suggestion")):
                    display_title = settings.title_text.strip()
                else:
                    display_title = base_title

            # Ensure clip status reflects this clip's unique title and base_title
            clip_status["title"] = display_title or base_title
            clip_status["base_title"] = base_title

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

        except Exception as e:
            logger.error(f"Error rendering clip {idx} in batch {batch_id}: {e}")
            clip_status["status"] = "error"
            clip_status["error_message"] = str(e)
            clip_status["error"] = str(e)
            clip_status.pop("download_note", None)

        batch["current_clip_index"] = idx + 1

    # Generate ZIP bundle for the batch with title-based filenames and duplicate handling
    try:
        completed_clips = [c for c in batch["clips"] if c.get("status") == "completed" and c.get("download_url")]
        if completed_clips:
            zip_filename = f"xoraclips_{batch_id}.zip"
            zip_path = video_engine.EXPORTS_DIR / zip_filename
            title_counts: Dict[str, int] = {}
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                for c in completed_clips:
                    fname = c["download_url"].split("/")[-1]
                    fpath = video_engine.EXPORTS_DIR / fname
                    if fpath.exists():
                        raw_title = (c.get("base_title") or c.get("title") or "").strip()
                        clean_title = re.sub(r'[\\/*?:"<>|]', "", raw_title) or f"clip_{c.get('clip_index', 1)}"
                        fn_pfx = re.sub(r'[\\/*?:"<>|]', "", settings.file_name_prefix or "")
                        fn_sfx = re.sub(r'[\\/*?:"<>|]', "", settings.file_name_suffix or "")
                        formatted_name = f"{fn_pfx}{clean_title}{fn_sfx}".strip() or clean_title
                        count = title_counts.get(formatted_name, 0)
                        title_counts[formatted_name] = count + 1
                        arc_name = f"{formatted_name}.mp4" if count == 0 else f"{formatted_name} ({count}).mp4"
                        zipf.write(fpath, arcname=arc_name)
            batch["zip_url"] = f"/api/download-batch-zip/{batch_id}"
        else:
            batch["zip_url"] = None
    except Exception as e:
        logger.warning(f"Failed to create batch zip: {e}")

    # Determine overall status and error messaging
    failed_clips = [c for c in batch["clips"] if c.get("status") == "error"]
    completed_clips = [c for c in batch["clips"] if c.get("status") == "completed"]

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

    batch_id = f"batch_{int(time.time())}_{uuid.uuid4().hex[:6]}"

    pfx = (request.settings.title_prefix or "") if request.settings else ""
    sfx = (request.settings.title_suffix or "") if request.settings else ""

    clips_status = []
    for idx, c in enumerate(request.clips):
        base_t = (c.get("custom_title") or c.get("title_suggestion") or c.get("title") or f"Clip {idx+1}").strip()
        full_t = f"{pfx}{base_t}{sfx}".strip() if (pfx or sfx) else base_t
        clips_status.append({
            "clip_index": idx,
            "title": full_t,
            "base_title": base_t,
            "status": "pending",
            "progress_percent": 0
        })

    RENDER_BATCHES[batch_id] = {
        "batch_id": batch_id,
        "total_clips": len(request.clips),
        "current_clip_index": 0,
        "overall_status": "running",
        "clips": clips_status,
        "zip_url": None
    }

    background_tasks.add_task(process_batch_rendering, batch_id, request)
    return {"batch_id": batch_id, "total_clips": len(request.clips)}


@router.get("/api/render-progress/{batch_id}")
async def get_render_progress(batch_id: str):
    if batch_id not in RENDER_BATCHES:
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
    clean_id = os.path.basename(batch_id)
    safe_name = f"xoraclips_{clean_id}.zip"
    file_path = video_engine.EXPORTS_DIR / safe_name
    if not file_path.exists():
        # Attempt to package any completed clips for this batch on the fly
        job = RENDER_BATCHES.get(batch_id)
        if job and job.get("clips"):
            try:
                title_counts: Dict[str, int] = {}
                with zipfile.ZipFile(file_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                    for c in job["clips"]:
                        c_out = c.get("output_path")
                        if not c_out and c.get("download_url"):
                            fname = c["download_url"].split("/")[-1]
                            c_out = str(video_engine.EXPORTS_DIR / fname)
                        if c_out and os.path.exists(c_out):
                            raw_title = (c.get("title") or "").strip()
                            clean_title = re.sub(r'[\\/*?:"<>|]', "", raw_title) or os.path.splitext(os.path.basename(c_out))[0]
                            count = title_counts.get(clean_title, 0)
                            title_counts[clean_title] = count + 1
                            arc_name = f"{clean_title}.mp4" if count == 0 else f"{clean_title} ({count}).mp4"
                            zipf.write(c_out, arcname=arc_name)
            except Exception as e:
                logger.error(f"Error packaging batch zip on the fly: {e}")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Batch zip file not found")
    return FileResponse(file_path, media_type="application/zip", filename=safe_name)


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
