"""
Downloads: rendered files, and background jobs for the raw source video and
raw clips. Moved out of main.py unchanged (#60).
"""
import asyncio
import logging
import os
import re
import shutil
import subprocess
import time
import uuid
from typing import Dict, Optional
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

try:
    from backend.video_engine import (
        ACTIVE_ENCODER_ARGS, ACTIVE_ENCODER_NAME, EXPORTS_DIR, TEMP_DIR,
        download_clip_segment, download_full_raw_video, download_timeouts,
    )
except ImportError:
    from video_engine import (
        ACTIVE_ENCODER_ARGS, ACTIVE_ENCODER_NAME, EXPORTS_DIR, TEMP_DIR,
        download_clip_segment, download_full_raw_video, download_timeouts,
    )

logger = logging.getLogger("xoraclips")
router = APIRouter()


@router.get("/api/download-rendered/{file_name}")
def download_rendered_file(file_name: str, title: Optional[str] = None):
    safe_name = os.path.basename(file_name)
    file_path = EXPORTS_DIR / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Rendered clip not found")

    # If title provided, sanitize and use as download filename
    dl_filename = safe_name
    if title and title.strip():
        clean_title = re.sub(r'[\\/*?:"<>|]', "", title.strip())
        if clean_title:
            dl_filename = f"{clean_title}.mp4" if not clean_title.lower().endswith(".mp4") else clean_title

    return FileResponse(file_path, media_type="video/mp4", filename=dl_filename)


class RawVideoDownloadRequest(BaseModel):
    video_url: str
    video_id: str
    title: Optional[str] = None


raw_download_jobs: Dict[str, dict] = {}


async def run_raw_download_job(job_id: str, v_url: str, out_path: str, filename: str, download_title: Optional[str] = None):
    def on_progress(p: dict):
        if job_id in raw_download_jobs:
            raw_download_jobs[job_id]["progress_percent"] = p.get("percent", 0.0)
            raw_download_jobs[job_id]["downloaded"] = p.get("downloaded", "")
            raw_download_jobs[job_id]["total"] = p.get("total", "")
            raw_download_jobs[job_id]["speed"] = p.get("speed", "")
            raw_download_jobs[job_id]["eta"] = p.get("eta", "")

    try:
        raw_download_jobs[job_id]["status"] = "downloading"
        await asyncio.to_thread(download_full_raw_video, v_url, out_path, on_progress)
        raw_download_jobs[job_id]["status"] = "ready"
        raw_download_jobs[job_id]["progress_percent"] = 100.0
        dl_name = download_title or filename
        raw_download_jobs[job_id]["download_url"] = f"/api/download-rendered/{filename}?title={quote(dl_name)}"
        raw_download_jobs[job_id]["filename"] = f"{dl_name}.mp4" if not dl_name.endswith(".mp4") else dl_name
    except Exception as e:
        logger.error(f"Raw video download job {job_id} failed: {e}")
        raw_download_jobs[job_id]["status"] = "failed"
        raw_download_jobs[job_id]["error"] = str(e)


@router.post("/api/download-raw-video")
async def handle_download_raw_video(req: RawVideoDownloadRequest, background_tasks: BackgroundTasks):
    v_url = req.video_url.strip() if req.video_url else ""
    if not v_url.startswith("http"):
        v_url = f"https://www.youtube.com/watch?v={req.video_id or v_url}"

    job_id = str(uuid.uuid4())[:8]
    safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', req.video_id or "youtube_video")
    filename = f"{safe_id}_raw_{int(time.time())}.mp4"
    out_path = str(EXPORTS_DIR / filename)

    clean_title = re.sub(r'[\\/*?:"<>|]', "", (req.title or "").strip())
    download_title = f"{clean_title} (Full Video)" if clean_title else f"{safe_id} (Full Video)"

    raw_download_jobs[job_id] = {
        "job_id": job_id,
        "status": "starting",
        "progress_percent": 0.0,
        "downloaded": "",
        "total": "",
        "speed": "",
        "eta": "",
        "download_url": None,
        "filename": f"{download_title}.mp4",
        "error": None
    }

    background_tasks.add_task(run_raw_download_job, job_id, v_url, out_path, filename, download_title)
    return {"job_id": job_id, "status": "starting"}


@router.get("/api/download-raw-status/{job_id}")
async def get_raw_download_status(job_id: str):
    job = raw_download_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Download job not found")
    return job


class RawClipDownloadRequest(BaseModel):
    video_url: str
    video_id: str
    start_time: float
    end_time: float
    title: str


raw_clip_download_jobs: Dict[str, dict] = {}


async def run_raw_clip_download_job(
    job_id: str,
    v_url: str,
    video_id: str,
    start_time: float,
    end_time: float,
    title: str
):
    clean_title = re.sub(r'[\\/*?:"<>|]', "", (title or "clip").strip())
    if not clean_title:
        clean_title = f"clip_{int(start_time)}_{int(end_time)}"
    download_title = f"{clean_title} (raw)"
    safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', video_id or "clip")
    seg_filename = f"{safe_id}_clip_{int(start_time)}_{int(end_time)}_{int(time.time())}_raw.mp4"
    out_path = EXPORTS_DIR / seg_filename

    try:
        raw_clip_download_jobs[job_id]["status"] = "downloading"
        raw_clip_download_jobs[job_id]["progress_percent"] = 25.0

        # Optimization: Check if a full raw video already exists locally in EXPORTS_DIR or TEMP_DIR
        local_candidates = list(EXPORTS_DIR.glob(f"*{safe_id}*.mp4")) + list(TEMP_DIR.glob(f"*{safe_id}*.mp4"))
        source_video = None
        for candidate in local_candidates:
            if candidate.exists() and candidate.stat().st_size > 5 * 1024 * 1024:
                # Avoid using a small trimmed clip segment as source
                if "_clip_" not in candidate.name and candidate.name != seg_filename:
                    source_video = str(candidate)
                    break

        duration_sec = max(1.0, end_time - start_time)
        # Issue #34: re-encoding a 3-minute clip on the CPU can take longer than 90s.
        trim_timeout = download_timeouts(duration_sec)["trim"]

        success = False
        if source_video and os.path.exists(source_video):
            try:
                logger.info(f"Trimming local video with {ACTIVE_ENCODER_NAME} for clip {download_title} ({start_time}-{end_time})")
                trim_cmd = [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", str(start_time),
                    "-i", source_video,
                    "-t", str(duration_sec),
                    *ACTIVE_ENCODER_ARGS,
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-avoid_negative_ts", "make_zero",
                    "-movflags", "+faststart",
                    str(out_path)
                ]
                await asyncio.to_thread(subprocess.run, trim_cmd, check=True, timeout=trim_timeout)
                if out_path.exists() and out_path.stat().st_size > 1000:
                    success = True
            except Exception as trim_err:
                logger.warning(f"Hardware trimming failed ({trim_err}), retrying with CPU libx264...")
                try:
                    cpu_trim_cmd = [
                        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                        "-ss", str(start_time),
                        "-i", source_video,
                        "-t", str(duration_sec),
                        "-c:v", "libx264",
                        "-preset", "veryfast",
                        "-crf", "20",
                        "-c:a", "aac",
                        "-b:a", "192k",
                        "-avoid_negative_ts", "make_zero",
                        "-movflags", "+faststart",
                        str(out_path)
                    ]
                    await asyncio.to_thread(subprocess.run, cpu_trim_cmd, check=True, timeout=trim_timeout)
                    if out_path.exists() and out_path.stat().st_size > 1000:
                        success = True
                except Exception as cpu_err:
                    logger.warning(f"CPU trimming also failed ({cpu_err}), falling back to direct stream download...")

        if not success:
            logger.info(f"Downloading clip segment from YouTube for {download_title} ({start_time}-{end_time})")
            temp_name = f"temp_{seg_filename}"
            downloaded_temp = await asyncio.to_thread(
                download_clip_segment,
                v_url,
                start_time,
                end_time,
                temp_name
            )
            if downloaded_temp and os.path.exists(downloaded_temp):
                if out_path.exists():
                    try:
                        out_path.unlink()
                    except Exception:
                        pass
                # Fast timestamp and keyframe normalization to eliminate any playback stutter
                fix_cmd = [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-i", downloaded_temp,
                    "-c", "copy",
                    "-avoid_negative_ts", "make_zero",
                    "-movflags", "+faststart",
                    str(out_path)
                ]
                try:
                    await asyncio.to_thread(subprocess.run, fix_cmd, check=True, timeout=45)
                    if out_path.exists() and out_path.stat().st_size > 1000:
                        success = True
                        try:
                            os.unlink(downloaded_temp)
                        except Exception:
                            pass
                except Exception:
                    shutil.move(downloaded_temp, str(out_path))
                    if out_path.exists() and out_path.stat().st_size > 1000:
                        success = True

        if success and out_path.exists() and out_path.stat().st_size > 1000:
            raw_clip_download_jobs[job_id]["status"] = "ready"
            raw_clip_download_jobs[job_id]["progress_percent"] = 100.0
            raw_clip_download_jobs[job_id]["download_url"] = f"/api/download-rendered/{seg_filename}?title={quote(download_title)}"
            raw_clip_download_jobs[job_id]["filename"] = f"{download_title}.mp4"
            logger.info(f"Raw clip '{download_title}' ready at {out_path}")
        else:
            raise RuntimeError("Generated clip file is missing or invalid.")

    except Exception as e:
        logger.error(f"Raw clip download job {job_id} failed: {e}")
        raw_clip_download_jobs[job_id]["status"] = "failed"
        raw_clip_download_jobs[job_id]["error"] = str(e)


@router.post("/api/download-raw-clip")
async def handle_download_raw_clip(req: RawClipDownloadRequest, background_tasks: BackgroundTasks):
    v_url = req.video_url.strip() if req.video_url else ""
    if not v_url.startswith("http"):
        v_url = f"https://www.youtube.com/watch?v={req.video_id or v_url}"

    job_id = str(uuid.uuid4())[:8]
    clean_title = re.sub(r'[\\/*?:"<>|]', "", (req.title or "clip").strip()) or "clip"
    download_title = f"{clean_title} (raw)"

    raw_clip_download_jobs[job_id] = {
        "job_id": job_id,
        "status": "starting",
        "progress_percent": 0.0,
        "title": download_title,
        "download_url": None,
        "filename": f"{download_title}.mp4",
        "error": None
    }

    background_tasks.add_task(
        run_raw_clip_download_job,
        job_id,
        v_url,
        req.video_id,
        req.start_time,
        req.end_time,
        req.title
    )
    return {"job_id": job_id, "status": "starting"}


@router.get("/api/download-raw-clip-status/{job_id}")
async def get_raw_clip_download_status(job_id: str):
    job = raw_clip_download_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Clip download job not found")
    return job
