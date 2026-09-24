"""
Clip boundaries (issue #35): line clip starts and ends up with transcript lines
and sentences so a clip does not open or close in the middle of one.

Gemini's start_time/end_time used to be taken as-is. Here each end is moved
to the edge of the line it falls in:

- start inside a line  -> back to that line's start
- end inside a line    -> forward to that line's end, plus a short tail
- in a gap between lines the time is left alone

YouTube auto captions roll: nearly every line stays on screen until the line
after next starts (in the saved transcripts 97-99% of lines overlap the next
one). The spoken part of a line therefore ends when the next line starts, so
a line's end here is min(its own end, the next line's start). The tail only
fills real silence and never reaches into the next line.

The prompt shows Gemini times rounded to 0.1s, so Gemini answers 140.9 for a
line that starts at 140.88. A time within EDGE_TOLERANCE of a line edge is
that edge; without this, 140.9 would count as "inside" the next line and pull
the whole line (~3s) into the clip.

Caption lines are not sentences, so ending on a line edge can still cut a
sentence in half (measured in #35: almost every clip did). When the
transcript has punctuation (at least PUNCTUATED_SHARE of lines hold . ? !),
the end is moved forward to the next sentence end, at most SENTENCE_REACH
seconds past Gemini's end. There are no word times, so a sentence end inside
a line is estimated from its character position. Transcripts without
punctuation keep the line edge. A prompt that told Gemini lines are not
sentences was tried in #35 and made clips shorter without ending them better,
so it is not used.

Each end moves at most MAX_SHIFT seconds to a line edge, stays inside
[lo, hi] (the range the user chose), and snapping never makes two clips
overlap that did not before.
"""
import bisect
import re
from typing import List, Optional, Sequence, Tuple

TAIL_SECONDS = 0.4
MAX_SHIFT_SECONDS = 8.0
# Half of the 0.1s rounding in the prompt, plus float slack.
EDGE_TOLERANCE_SECONDS = 0.06
SENTENCE_REACH_SECONDS = 8.0
# After a sentence end estimated inside a line; the next word is right there.
MID_LINE_TAIL_SECONDS = 0.15
PUNCTUATED_SHARE = 0.15

# A . ? ! (possibly repeated, possibly followed by a closing quote or
# bracket) that ends a word.
_SENTENCE_END = re.compile(r"[.?!]+[\"')\]]*(?=\s|$)")


class Lines:
    """Transcript lines, sorted, with their spoken ends and sentence ends."""

    def __init__(self, lines: Sequence[dict]):
        spans = sorted(
            (float(l.get("start", 0.0)), float(l.get("end", 0.0)), str(l.get("text", "")).strip())
            for l in lines
        )
        self.starts: List[float] = [s for s, _, _ in spans]
        self.ends: List[float] = []
        for i, (s, e, _) in enumerate(spans):
            nxt = self.starts[i + 1] if i + 1 < len(spans) else None
            spoken = e if nxt is None or nxt <= s else min(e, nxt)
            self.ends.append(max(s, spoken))
        self.edges: List[float] = sorted(set(self.starts + self.ends))

        # (time, line index, ends the line) for every sentence end.
        self.stops: List[Tuple[float, int, bool]] = []
        with_stop = 0
        for i, (_, _, text) in enumerate(spans):
            found = list(_SENTENCE_END.finditer(text))
            with_stop += bool(found)
            s, e = self.starts[i], self.ends[i]
            for m in found:
                at_line_end = not text[m.end():].strip()
                at = e if at_line_end else s + (e - s) * m.end() / len(text)
                self.stops.append((at, i, at_line_end))
        self.stops.sort()
        self._stop_times = [t for t, _, _ in self.stops]
        self.punctuated = bool(spans) and with_stop / len(spans) >= PUNCTUATED_SHARE

    def _on_edge(self, t: float) -> float:
        """The line edge t was rounded from, or t itself."""
        i = bisect.bisect_left(self.edges, t)
        near = [e for e in self.edges[max(0, i - 1):i + 1] if abs(e - t) <= EDGE_TOLERANCE_SECONDS]
        return min(near, key=lambda e: abs(e - t)) if near else t

    def _containing(self, t: float) -> Optional[int]:
        """Index of the line whose spoken span holds t (start <= t < end)."""
        i = bisect.bisect_right(self.starts, t) - 1
        if i >= 0 and self.starts[i] <= t < self.ends[i]:
            return i
        return None

    def _tail(self, i: int, hi: float) -> float:
        """Line i's end plus the tail, kept out of the next line and inside hi."""
        end = self.ends[i]
        tailed = end + TAIL_SECONDS
        nxt = self.starts[i + 1] if i + 1 < len(self.starts) else None
        if nxt is not None and nxt >= end:
            tailed = min(tailed, nxt)
        return min(hi, tailed)

    def snap_start(self, t: float, lo: float) -> float:
        t = max(lo, self._on_edge(t))
        i = self._containing(t)
        if i is None:
            return t
        s = self.starts[i]
        if t - s > MAX_SHIFT_SECONDS:
            return t
        return max(lo, s)

    def snap_end(self, t: float, hi: float) -> float:
        t = min(hi, self._on_edge(t))
        # A line that ends exactly at t still gets its tail; a line that
        # starts exactly at t is not part of the clip.
        i = bisect.bisect_left(self.starts, t) - 1
        if i < 0 or not (self.starts[i] < t <= self.ends[i]):
            return t
        if self.ends[i] - t > MAX_SHIFT_SECONDS:
            return t
        return self._tail(i, hi)

    def _stop_end(self, k: int, hi: float) -> float:
        """Where a clip ending on stop k ends: its time plus the right tail."""
        at, i, at_line_end = self.stops[k]
        if at_line_end:
            return self._tail(i, hi)
        # Inside a line the next word follows straight away: a short tail.
        return min(hi, at + MID_LINE_TAIL_SECONDS, self.ends[i])

    def sentence_end(self, t: float, hi: float) -> Optional[float]:
        """The end of the sentence running at t, or None.

        None when the transcript has no punctuation or the sentence runs on
        more than SENTENCE_REACH seconds.
        """
        if not self.punctuated:
            return None
        t = min(hi, self._on_edge(t))
        tol = EDGE_TOLERANCE_SECONDS
        k = bisect.bisect_left(self._stop_times, t - TAIL_SECONDS - tol)
        while k < len(self.stops):
            at, _, at_line_end = self.stops[k]
            tail = TAIL_SECONDS if at_line_end else MID_LINE_TAIL_SECONDS
            if at - tol <= t <= at + tail + tol:
                return self._stop_end(k, hi)  # t already ends this sentence
            if at > t:
                if at > t + SENTENCE_REACH_SECONDS:
                    return None
                return self._stop_end(k, hi)
            k += 1  # a stop before t with words after it: keep looking
        return None


    def last_end_before(self, limit: float, hi: float) -> Optional[float]:
        """The latest clean clip end at or before limit, or None.

        A sentence end when the transcript has punctuation, otherwise a line
        end with its tail (without the tail if only that fits).
        """
        if self.punctuated:
            k = bisect.bisect_right(self._stop_times, limit) - 1
            while k >= 0:
                end = self._stop_end(k, hi)
                if end <= limit:
                    return end
                k -= 1
        best = None
        for i, e in enumerate(self.ends):
            if e > limit:
                continue
            tailed = self._tail(i, hi)
            end = tailed if tailed <= limit else e
            if best is None or end > best:
                best = end
        return best


def snap_clip(start: float, end: float, lines: Lines, lo: float, hi: float) -> Tuple[float, float]:
    """One clip's (start, end) moved to line and sentence edges; unchanged if that goes wrong."""
    s = lines.snap_start(start, lo)
    sentence = lines.sentence_end(end, hi)
    e = sentence if sentence is not None else lines.snap_end(end, hi)
    if e <= s:
        return start, end
    return round(s, 2), round(e, 2)


def snap_clips(
    clips: Sequence[Tuple[float, float]],
    transcript: Sequence[dict],
    lo: float,
    hi: float,
) -> List[Tuple[float, float]]:
    """Snap every (start, end), in input order, without creating new overlaps."""
    lines = Lines(transcript)
    snapped = [list(snap_clip(s, e, lines, lo, hi)) for s, e in clips]

    order = sorted(range(len(clips)), key=lambda k: clips[k][0])
    for n, a in enumerate(order):
        for b in order[n + 1:]:
            # Clips Gemini made overlapping stay as they are; only undo
            # overlap that snapping caused.
            a_end, b_start = clips[a][1], clips[b][0]
            if a_end <= b_start and snapped[a][1] > snapped[b][0]:
                snapped[a][1] = min(snapped[a][1], b_start)
                snapped[b][0] = max(snapped[b][0], snapped[a][1])

    return [(s, e) for s, e in snapped]
