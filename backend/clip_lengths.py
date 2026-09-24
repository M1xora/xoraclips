"""
Clip lengths (issue #34): the target durations the user can pick, what the
prompt asks Gemini for, and the limits applied after Gemini answers.

The durations used to be spread over main.py as string lookups; an unknown
value silently became 30s. Now the request only accepts the values below.

- 2m and 3m clips must hold one complete idea (setup to conclusion).
- No clip is longer than MAX_CLIP_SECONDS (YouTube Shorts allows 3 minutes).
  The limit runs after clip_bounds, which can lengthen a clip, and cuts back
  to the last transcript line edge inside the limit.
- The clip count asked from Gemini never exceeds what fits in the searched
  span without overlap (10 clips of 3 minutes do not fit in 15 minutes).
- Backup clips (when Gemini returns none) are placed around the peaks, do
  not overlap, and stay inside the searched span.
"""
import bisect
from typing import Dict, List, Literal, Optional, Sequence, Tuple

Duration = Literal["15s", "30s", "60s", "120s", "180s"]

# duration -> (shortest, longest, target) in seconds
DURATIONS: Dict[str, Tuple[int, int, int]] = {
    "15s": (10, 20, 15),
    "30s": (20, 40, 30),
    "60s": (45, 75, 60),
    "120s": (90, 130, 120),
    "180s": (140, 175, 180),
}
LONG_DURATIONS = ("120s", "180s")

# YouTube Shorts takes up to 3 minutes; one second of margin.
MAX_CLIP_SECONDS = 179.0

BACKUP_CLIPS = 5


def prompt_range(duration: str) -> str:
    shortest, longest, _ = DURATIONS[duration]
    return f"{shortest}-{longest}s"


def target_seconds(duration: str) -> float:
    return float(DURATIONS[duration][2])


def prompt_rules(duration: str) -> str:
    """Extra prompt rules for long clips; empty for the short ones."""
    if duration not in LONG_DURATIONS:
        return ""
    return (
        "LONG CLIP RULES:\n"
        "- Each clip must hold ONE complete idea, story or argument: how it starts, the point, "
        "and how it ends. Never stop in the middle of an explanation.\n"
        "- The first seconds must still hook the viewer.\n\n"
    )


def fitting_clips(span: float, duration: str) -> int:
    """How many clips of the target length fit in span without overlapping."""
    return max(1, int(span // target_seconds(duration)))


def clip_count_range(
    requested: Optional[int], is_long_video: bool, span: float, duration: str
) -> Tuple[str, Optional[int]]:
    """The clip count range for the prompt, and the capped count if it was capped.

    The ranges are the ones main.py used before #34; only the upper end is
    brought down when it cannot fit.
    """
    if requested:
        n = requested
        if n <= 5:
            low, high = max(1, n - 1), n + 2
        elif n <= 10:
            low, high = max(1, n - 2), n + 3
        else:
            low, high = n - 5, n + 5
    else:
        low, high = (15, 60) if is_long_video else (10, 30)

    fit = fitting_clips(span, duration)
    capped = None
    if high > fit:
        high = fit
        low = min(low, high)
        if requested and requested > fit:
            capped = fit
    return f"{low}-{high}", capped


def cap_length(start: float, end: float, edges: Sequence[float]) -> float:
    """end, or the last line edge within MAX_CLIP_SECONDS of start."""
    if end - start <= MAX_CLIP_SECONDS:
        return end
    limit = start + MAX_CLIP_SECONDS
    i = bisect.bisect_right(edges, limit) - 1
    # An edge far back would throw away most of the clip; cut at the limit then.
    if i >= 0 and edges[i] > start + MAX_CLIP_SECONDS / 2:
        return round(edges[i], 2)
    return round(limit, 2)


def backup_windows(
    peaks: Sequence[float], duration: str, lo: float, hi: float, count: int = BACKUP_CLIPS
) -> List[Tuple[float, float, float]]:
    """(start, end, peak) for backup clips around the strongest moments.

    peaks is ordered strongest first. A clip starts a quarter of its length
    before the peak so the lead-up is in it, stays inside [lo, hi], and does
    not overlap an earlier one.
    """
    target = target_seconds(duration)
    chosen: List[Tuple[float, float, float]] = []
    for peak in peaks:
        if not (lo <= peak <= hi):
            continue
        start = max(lo, peak - target / 4)
        end = min(hi, start + target)
        start = max(lo, end - target)  # near hi: shift back, keep the length
        if end <= start:
            continue
        if any(start < b and a < end for a, b, _ in chosen):
            continue
        chosen.append((round(start, 2), round(end, 2), peak))
        if len(chosen) >= count:
            break
    return chosen
