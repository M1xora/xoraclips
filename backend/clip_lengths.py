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
- 2m/3m clips Gemini made too short are widened to the shortest length
  (#38), ending on a sentence or line edge.
"""
from typing import Dict, List, Literal, Optional, Sequence, Tuple

try:
    from backend.clip_bounds import Lines
except ImportError:
    from clip_bounds import Lines

Duration = Literal["15s", "30s", "60s", "120s", "180s"]

# duration -> (shortest, longest, target) in seconds
DURATIONS: Dict[str, Tuple[int, int, int]] = {
    "15s": (10, 20, 15),
    "30s": (20, 40, 30),
    "60s": (45, 75, 60),
    "120s": (90, 130, 120),
    # The target stays under MAX_CLIP_SECONDS: backup clips and the clip
    # count are built from it.
    "180s": (140, 175, 175),
}
LONG_DURATIONS = ("120s", "180s")

# YouTube Shorts takes up to 3 minutes; one second of margin.
MAX_CLIP_SECONDS = 179.0

BACKUP_CLIPS = 5

# Share of the searched span clips may cover: intros, outros and filler are
# not clip material, and Gemini needs room to choose (10 x 3 minutes asked
# from 15 minutes would force it to tile the whole video).
MAX_COVERAGE = 0.6


def label(duration: str) -> str:
    """The label the form shows: 15s, 30s, 60s, 2m, 3m."""
    seconds = int(duration.rstrip("s"))
    return f"{seconds // 60}m" if seconds >= 120 else duration


def prompt_range(duration: str) -> str:
    shortest, longest, _ = DURATIONS[duration]
    return f"{shortest}-{longest}s"


def target_seconds(duration: str) -> float:
    return float(DURATIONS[duration][2])


def prompt_rules(duration: str) -> str:
    """Extra prompt rules for long clips; empty for the short ones."""
    if duration not in LONG_DURATIONS:
        return ""
    shortest, longest, _ = DURATIONS[duration]
    return (
        "LONG CLIP RULES:\n"
        f"- HARD RULE: every clip is {shortest}-{longest} seconds long (end_time - start_time). "
        f"A clip under {shortest} seconds is wrong for this request: extend it with the lead-up "
        "and the conclusion around the moment instead of returning a short clip.\n"
        "- Each clip must hold ONE complete idea, story or argument: how it starts, the point, "
        "and how it ends. Never stop in the middle of an explanation.\n"
        "- The first seconds must still hook the viewer.\n\n"
    )


def fitting_clips(span: float, duration: str) -> int:
    """How many clips of the target length fit in MAX_COVERAGE of span."""
    return max(1, int(span * MAX_COVERAGE // target_seconds(duration)))


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


def cap_length(start: float, end: float, lines: Lines, hi: float) -> float:
    """end, or the last clean end (sentence, or line + tail) within MAX_CLIP_SECONDS."""
    if end - start <= MAX_CLIP_SECONDS:
        return end
    limit = start + MAX_CLIP_SECONDS
    best = lines.last_end_before(limit, hi)
    # An end far back would throw away most of the clip; cut at the limit then.
    if best is not None and best > start + MAX_CLIP_SECONDS / 2:
        return round(best, 2)
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


# How the missing seconds of a too-short clip are split: most of it after
# the clip (where the story goes on), the rest before it (the lead-up).
STRETCH_AFTER_SHARE = 0.75


def stretch_short_clips(
    bounds: Sequence[Tuple[float, float]], lines: Lines, duration: str, lo: float, hi: float
) -> List[Tuple[float, float]]:
    """2m/3m clips under the shortest length, widened to reach it (#38).

    Gemini (seen with gemini-3.5-flash-lite) can ignore the length rule and
    return 40s clips for 2m. Like OpusClip, the length stays a preference,
    but a clip is only widened up to the shortest length, not the target,
    so as little as possible is added that Gemini did not pick. The new ends
    are moved to a line start and a sentence/line end, never into another
    clip, and stay inside [lo, hi]. Other durations are left alone.
    """
    out = [list(b) for b in bounds]
    if duration not in LONG_DURATIONS:
        return [(s, e) for s, e in out]
    shortest = float(DURATIONS[duration][0])

    for k in sorted(range(len(out)), key=lambda n: out[n][0]):
        s, e = out[k]
        if e - s >= shortest:
            continue
        # Neighbours as they are now; clips that already overlap this one
        # (Gemini's own overlaps) are not walls.
        before = max([lo] + [b for j, (a, b) in enumerate(out) if j != k and b <= s])
        after = min([hi] + [a for j, (a, b) in enumerate(out) if j != k and a >= e])
        missing = shortest - (e - s)
        add_after = min(max(0.0, after - e), missing * STRETCH_AFTER_SHARE)
        add_before = min(max(0.0, s - before), missing - add_after)
        add_after = min(max(0.0, after - e), missing - add_before)

        new_s = max(before, lines.snap_start(s - add_before, before))
        target_end = e + add_after
        sentence = lines.sentence_end(target_end, after)
        new_e = min(after, sentence if sentence is not None else lines.snap_end(target_end, after))
        if new_e > new_s and (new_s, new_e) != (s, e):
            out[k] = [round(new_s, 2), round(new_e, 2)]
    return [(s, e) for s, e in out]
