"""
Preview frames and speaker face boxes for the Studio. Moved out of main.py
unchanged (#60).
"""
import asyncio
import logging
import os

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

try:
    from backend import video_engine
    from backend.validation import MAX_VIDEO_SECONDS, require_video_id
    from backend.video_engine import detect_speaker_face_box, extract_clip_frame, extract_clip_frame_info
except ImportError:
    import video_engine
    from validation import MAX_VIDEO_SECONDS, require_video_id
    from video_engine import detect_speaker_face_box, extract_clip_frame, extract_clip_frame_info

logger = logging.getLogger("xoraclips")
router = APIRouter()


# Seconds into the video: finite, 0 to 24 hours (issue #42).
FRAME_TIMESTAMP = Query(0.0, ge=0, le=MAX_VIDEO_SECONDS, allow_inf_nan=False)


@router.get("/api/clip-frame")
async def get_clip_frame(video_id: str, timestamp: float = FRAME_TIMESTAMP):
    """
    The video frame at timestamp for the preview backdrop. When YouTube gives
    no frame for that second, a stand-in (another second, or the thumbnail)
    that the browser must not keep (issue #44).
    Takes only a video ID (issue #42): the YouTube URL is built here, never sent.
    """
    require_video_id(video_id)
    try:
        frame_path, exact = await asyncio.to_thread(extract_clip_frame_info, video_id, timestamp)
        if frame_path and os.path.exists(frame_path):
            cache = "public, max-age=86400" if exact else "no-store"
            return FileResponse(frame_path, media_type="image/jpeg", headers={"Cache-Control": cache})
    except Exception as e:
        logger.warning(f"Failed to serve extracted frame for {video_id}: {e}")

    raise HTTPException(status_code=404, detail="Real video frame could not be extracted yet")


@router.get("/api/detect-face")
async def detect_face(video_id: str, timestamp: float = FRAME_TIMESTAMP):
    """
    Detects speaker face coordinates (cx, cy, w, h) on the video at timestamp.
    Returns normalized coordinates and the frame URL.
    Takes only a video ID (issue #42): the YouTube URL is built here, never sent.
    """
    require_video_id(video_id)
    default_res = {
        "found": False,
        "cx": 0.5,
        "cy": 0.35,
        "w": 0.25,
        "h": 0.25,
        "frame_url": f"/api/clip-frame?video_id={video_id}&timestamp={timestamp}"
    }
    try:
        # First try to extract or get the cached frame
        frame_path = await asyncio.to_thread(extract_clip_frame, video_id, timestamp)
        if frame_path and os.path.exists(frame_path):
            box = await asyncio.to_thread(detect_speaker_face_box, frame_path)
            box["frame_url"] = f"/api/clip-frame?video_id={video_id}&timestamp={timestamp}"
            return box

        # If frame extract didn't complete, check local candidates
        local_candidates = list(video_engine.TEMP_DIR.glob(f"*{video_id}*.mp4")) + list(video_engine.EXPORTS_DIR.glob(f"*{video_id}*.mp4"))
        for candidate in local_candidates:
            if candidate.exists() and candidate.stat().st_size > 10000 and "slice_" not in candidate.name:
                box = await asyncio.to_thread(detect_speaker_face_box, str(candidate))
                box["frame_url"] = f"/api/clip-frame?video_id={video_id}&timestamp={timestamp}"
                return box
    except Exception as e:
        logger.warning(f"Face detection API error: {e}")

    return default_res
