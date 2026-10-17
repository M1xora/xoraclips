"""
Why captions could not be fetched from YouTube, as short codes (issue #9).

When YouTube refuses this server (HTTP 429, IpBlocked, the Google "Sorry..."
page), every further request only makes the block last longer. So a block
is recognised in one place, stops every remaining tier, and is remembered
for a while so the next analyses do not knock again.

The user sees a short message per code (translated in the frontend); the
per-tier details go to the log only.
"""
import math
import re
import threading
import time
from typing import Callable, Optional

YOUTUBE_BLOCKED = "youtube_blocked"
CAPTIONS_DISABLED = "captions_disabled"
VIDEO_UNAVAILABLE = "video_unavailable"
AGE_RESTRICTED = "age_restricted"
VIDEO_LIVE = "video_live"
CAPTIONS_UNAVAILABLE = "captions_unavailable"

# English fallbacks; the frontend shows its own translation per code.
MESSAGES = {
    YOUTUBE_BLOCKED: "YouTube is refusing subtitle requests. Try again later, or upload subtitles manually.",
    CAPTIONS_DISABLED: "The creator turned subtitles off for this video. Upload subtitles manually to analyze it.",
    VIDEO_UNAVAILABLE: "This video is private or unavailable.",
    AGE_RESTRICTED: "This video is age-restricted, so its subtitles cannot be fetched. Upload subtitles manually.",
    VIDEO_LIVE: "This video is live or just ended, so YouTube has no subtitles yet. Try again later, or upload subtitles manually.",
    CAPTIONS_UNAVAILABLE: "No subtitles could be fetched for this video. Upload subtitles manually.",
}

STATUS = {
    YOUTUBE_BLOCKED: 429,
    CAPTIONS_DISABLED: 400,
    VIDEO_UNAVAILABLE: 404,
    AGE_RESTRICTED: 403,
    VIDEO_LIVE: 400,
    CAPTIONS_UNAVAILABLE: 400,
}

BLOCK_COOLDOWN_SECONDS = 600


class CaptionUnavailable(Exception):
    """Captions could not be fetched; `code` says why, `detail` is for the log."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or MESSAGES[code])
        self.code = code
        self.detail = detail


class YouTubeBlocked(CaptionUnavailable):
    """YouTube refused us. `retry_after` is how long we will stay away (seconds)."""

    def __init__(self, detail: str = "", retry_after: int = 0):
        super().__init__(YOUTUBE_BLOCKED, detail)
        self.retry_after = retry_after


_BLOCK_EXCEPTION_NAMES = {"IpBlocked", "RequestBlocked"}

# Phrases YouTube, youtube-transcript-api and yt-dlp use for a refusal.
_BLOCK_TEXT = re.compile(
    r"YouTube is blocking (?:your )?requests"
    r"|\bIpBlocked\b|\bRequestBlocked\b"
    r"|<title>Sorry\.\.\.</title>"
    r"|sending automated queries"
    r"|HTTP Error 429|Too Many Requests"
    r"|Sign in to confirm you.re not a bot",
    re.IGNORECASE,
)


def is_blocked_text(text: Optional[str]) -> bool:
    """For error text only (exceptions, CLI output), never for caption content."""
    return bool(text) and bool(_BLOCK_TEXT.search(text))


def is_blocked_exception(error: BaseException) -> bool:
    names = {cls.__name__ for cls in type(error).__mro__}
    return bool(names & _BLOCK_EXCEPTION_NAMES) or is_blocked_text(str(error))


def is_blocked_response(status_code: int, content_type: str = "", body: str = "") -> bool:
    """429, or the "Sorry..." HTML page (which can also come with another status)."""
    if status_code == 429:
        return True
    return "html" in (content_type or "").lower() and is_blocked_text(body[:4000])


def error_event(code: str, retry_after: Optional[int] = None) -> dict:
    """The SSE error payload for a code."""
    event = {"error": MESSAGES[code], "code": code, "status": STATUS[code]}
    if retry_after:
        event["retry_after"] = int(retry_after)
    return event


class BlockMemory:
    """
    Remembers a block for BLOCK_COOLDOWN_SECONDS. Server-wide on purpose:
    YouTube blocks the server's address, so every user is affected alike.
    Kept in memory only: a restart forgets it.
    """

    def __init__(self, seconds: int = BLOCK_COOLDOWN_SECONDS, clock: Callable[[], float] = time.monotonic):
        self.seconds = seconds
        self.clock = clock
        self._until = 0.0
        self._lock = threading.Lock()

    def remember(self) -> int:
        with self._lock:
            self._until = self.clock() + self.seconds
        return self.seconds

    def remaining(self) -> int:
        with self._lock:
            left = self._until - self.clock()
        return math.ceil(left) if left > 0 else 0


block_memory = BlockMemory()
