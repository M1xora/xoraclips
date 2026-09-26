"""
Checks on request values that several routes share: YouTube video IDs,
times inside a video, and text that becomes a file name (#64).
"""
import re
from typing import Optional

from fastapi import HTTPException
from pydantic import Field

try:
    from backend.video_engine import is_video_id
except ImportError:
    from video_engine import is_video_id

# Seconds into a video: finite, 0 to 24 hours (issue #42).
MAX_VIDEO_SECONDS = 24 * 3600
VIDEO_SECONDS = Field(ge=0, le=MAX_VIDEO_SECONDS, allow_inf_nan=False)


def require_video_id(video_id: Optional[str]) -> str:
    """The video ID if it is a valid YouTube ID, else a 400 error."""
    if not is_video_id(video_id):
        raise HTTPException(status_code=400, detail="Invalid YouTube video ID")
    return video_id


def check_time_range(start_time: float, end_time: float) -> None:
    """For a request model's validator: the end comes after the start."""
    if end_time <= start_time:
        raise ValueError("end_time must be greater than start_time")


def without_forbidden_characters(text: Optional[str]) -> str:
    """Text without the characters Windows refuses in a file name; spaces kept
    (a file name prefix like "Part 1 - " needs its own)."""
    return re.sub(r'[\\/*?:"<>|]', "", text or "")


def clean_file_title(text: Optional[str]) -> str:
    """A title for a file name: trimmed, without forbidden characters."""
    return without_forbidden_characters((text or "").strip())
