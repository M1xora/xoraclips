"""
Downloads: rendered files, and background jobs for the raw source video and
raw clips. The video is named only by its checked YouTube ID; the server
builds the URL (#64). Finished jobs are forgotten after an hour.
"""
import asyncio
import logging
import os
import re
import shutil
import subprocess
import time
from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator

try:
    from backend import video_engine
    from backend.job_store import JobStore, new_job_id
    from backend.validation import MAX_VIDEO_SECONDS, check_time_range, clean_file_title, require_video_id
    from backend.video_engine import (
        ACTIVE_ENCODER_ARGS, ACTIVE_ENCODER_NAME, download_clip_segment, download_full_raw_video,
        download_timeouts, watch_url,
    )
except ImportError:
    import video_engine
    from job_store import JobStore, new_job_id
    from validation import MAX_VIDEO_SECONDS, check_time_range, clean_file_title, require_video_id
    from video_engine import (
        ACTIVE_ENCODER_ARGS, ACTIVE_ENCODER_NAME, download_clip_segment, download_full_raw_video,
        download_timeouts, watch_url,
    )

logger = logging.getLogger("xoraclips")
router = APIRouter()

VIDEO_SECONDS = Field(ge=0, le=MAX_VIDEO_SECONDS, allow_inf_nan=False)
# A raw clip is a piece of the video; the whole video has its own download.
MAX_RAW_CLIP_SECONDS = 30 * 60
CPU_ENCODER_ARGS = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]


@router.get("/api/download-rendered/{file_name}")
def download_rendered_file(file_name: str, title: Optional[str] = None):
    safe_name = os.path.basename(file_name)
    file_path = video_engine.EXPORTS_DIR / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Rendered clip not found")

    # If title provided, sanitize and use as download filename
    dl_filename = safe_name
    clean_title = clean_file_title(title)
    if clean_title:
        dl_filename = f"{clean_title}.mp4" if not clean_title.lower().endswith(".mp4") else clean_title

    return FileResponse(file_path, media_type="video/mp4", filename=dl_filename)


# ── Raw source video ─────────────────────────────────────────────────────────

class RawVideoDownloadRequest(BaseModel):
    video_id: str
    video_url: Optional[str] = None   # still sent by the app; ignored (#64)
    title: Optional[str] = None


raw_download_jobs = JobStore()


def raw_video_title(title: Optional[str], video_id: str) -> str:
    """The download name of a full raw video."""
    return f"{clean_file_title(title) or video_id} (Full Video)"


async def run_raw_download_job(job_id: str, v_url: str, out_path: str, filename: str, download_title: str):
    job = raw_download_jobs[job_id]

    def on_progress(p: dict):
        job["progress_percent"] = p.get("percent", 0.0)
        job["downloaded"] = p.get("downloaded", "")
        job["total"] = p.get("total", "")
        job["speed"] = p.get("speed", "")
        job["eta"] = p.get("eta", "")

    try:
        job["status"] = "downloading"
        await asyncio.to_thread(download_full_raw_video, v_url, out_path, on_progress)
        job["status"] = "ready"
        job["progress_percent"] = 100.0
        job["download_url"] = f"/api/download-rendered/{filename}?title={quote(download_title)}"
    except Exception as e:
        logger.error(f"Raw video download job {job_id} failed: {e}")
        job["status"] = "failed"
        job["error"] = str(e)
    finally:
        raw_download_jobs.finish(job_id)


@router.post("/api/download-raw-video")
async def handle_download_raw_video(req: RawVideoDownloadRequest, background_tasks: BackgroundTasks):
    video_id = require_video_id(req.video_id)
    job_id = new_job_id()
    # The job ID keeps two downloads started in the same second apart.
    filename = f"{video_id}_raw_{int(time.time())}_{job_id[:8]}.mp4"
    out_path = str(video_engine.EXPORTS_DIR / filename)
    download_title = raw_video_title(req.title, video_id)

    raw_download_jobs.add(job_id, {
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
    })

    background_tasks.add_task(run_raw_download_job, job_id, watch_url(video_id), out_path, filename, download_title)
    return {"job_id": job_id, "status": "starting"}


@router.get("/api/download-raw-status/{job_id}")
async def get_raw_download_status(job_id: str):
    job = raw_download_jobs.lookup(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Download job not found")
    return job


# ── Raw clip ─────────────────────────────────────────────────────────────────

class RawClipDownloadRequest(BaseModel):
    video_id: str
    video_url: Optional[str] = None   # still sent by the app; ignored (#64)
    start_time: float = VIDEO_SECONDS
    end_time: float = VIDEO_SECONDS
    title: str

    @model_validator(mode="after")
    def _end_after_start(self):
        check_time_range(self.start_time, self.end_time)
        if self.end_time - self.start_time > MAX_RAW_CLIP_SECONDS:
            raise ValueError(f"A raw clip can be at most {MAX_RAW_CLIP_SECONDS // 60} minutes long")
        return self


raw_clip_download_jobs = JobStore()


def raw_clip_title(title: Optional[str], start_time: float, end_time: float) -> str:
    """The download name of a raw clip; the job and its status use the same one."""
    return f"{clean_file_title(title) or f'clip_{int(start_time)}_{int(end_time)}'} (raw)"


def _trim_command(source: str, start_time: float, duration_sec: float, out_path: str,
                  encoder_args: List[str]) -> List[str]:
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", str(start_time),
        "-i", source,
        "-t", str(duration_sec),
        *encoder_args,
        "-c:a", "aac",
        "-b:a", "192k",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        out_path,
    ]


def _local_full_video(video_id: str) -> Optional[str]:
    """A finished full raw video of this video already on disk. Only the
    app's own finished downloads count: yt-dlp's video-only streams
    (`.f137.mp4`) and half-merged files (`.temp.mp4`) have other names."""
    finished = re.compile(re.escape(video_id) + r"_raw_\d+(_[0-9a-f]{8})?\.mp4")
    for candidate in video_engine.EXPORTS_DIR.glob(f"{video_id}_raw_*.mp4"):
        if finished.fullmatch(candidate.name) and candidate.stat().st_size > 5 * 1024 * 1024:
            return str(candidate)
    return None


async def run_raw_clip_download_job(job_id: str, video_id: str, start_time: float, end_time: float,
                                    download_title: str):
    job = raw_clip_download_jobs[job_id]
    seg_filename = f"{video_id}_clip_{int(start_time)}_{int(end_time)}_{job_id[:8]}_raw.mp4"
    out_path = video_engine.EXPORTS_DIR / seg_filename

    def usable() -> bool:
        return out_path.exists() and out_path.stat().st_size > 1000

    try:
        job["status"] = "downloading"
        job["progress_percent"] = 25.0

        duration_sec = max(1.0, end_time - start_time)
        # Issue #34: re-encoding a 3-minute clip on the CPU can take longer than 90s.
        trim_timeout = download_timeouts(duration_sec)["trim"]

        success = False
        source_video = _local_full_video(video_id)
        if source_video:
            for encoder_name, encoder_args in ((ACTIVE_ENCODER_NAME, ACTIVE_ENCODER_ARGS), ("CPU libx264", CPU_ENCODER_ARGS)):
                try:
                    logger.info(f"Trimming local video with {encoder_name} for clip {download_title} ({start_time}-{end_time})")
                    cmd = _trim_command(source_video, start_time, duration_sec, str(out_path), encoder_args)
                    await asyncio.to_thread(subprocess.run, cmd, check=True, timeout=trim_timeout)
                    if usable():
                        success = True
                        break
                except Exception as trim_err:
                    logger.warning(f"Trimming with {encoder_name} failed ({trim_err})")

        if not success:
            logger.info(f"Downloading clip segment from YouTube for {download_title} ({start_time}-{end_time})")
            downloaded_temp = await asyncio.to_thread(
                download_clip_segment, watch_url(video_id), start_time, end_time, f"temp_{seg_filename}")
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
                    if usable():
                        success = True
                        try:
                            os.unlink(downloaded_temp)
                        except Exception:
                            pass
                except Exception:
                    shutil.move(downloaded_temp, str(out_path))
                    success = usable()

        if not (success and usable()):
            raise RuntimeError("Generated clip file is missing or invalid.")
        job["status"] = "ready"
        job["progress_percent"] = 100.0
        job["download_url"] = f"/api/download-rendered/{seg_filename}?title={quote(download_title)}"
        logger.info(f"Raw clip '{download_title}' ready at {out_path}")

    except Exception as e:
        logger.error(f"Raw clip download job {job_id} failed: {e}")
        job["status"] = "failed"
        job["error"] = str(e)
    finally:
        raw_clip_download_jobs.finish(job_id)


@router.post("/api/download-raw-clip")
async def handle_download_raw_clip(req: RawClipDownloadRequest, background_tasks: BackgroundTasks):
    video_id = require_video_id(req.video_id)
    job_id = new_job_id()
    download_title = raw_clip_title(req.title, req.start_time, req.end_time)

    raw_clip_download_jobs.add(job_id, {
        "job_id": job_id,
        "status": "starting",
        "progress_percent": 0.0,
        "title": download_title,
        "download_url": None,
        "filename": f"{download_title}.mp4",
        "error": None
    })

    background_tasks.add_task(
        run_raw_clip_download_job, job_id, video_id, req.start_time, req.end_time, download_title)
    return {"job_id": job_id, "status": "starting"}


@router.get("/api/download-raw-clip-status/{job_id}")
async def get_raw_clip_download_status(job_id: str):
    job = raw_clip_download_jobs.lookup(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Clip download job not found")
    return job
