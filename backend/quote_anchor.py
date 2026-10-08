"""
Finding a quote back in the transcript (issue #99).

Gemini is asked to copy the first and last sentence of each clip out of the
transcript. Those quotes are matched here against the transcript's own words,
and the times they are found at anchor the clip's bounds — instead of trusting
the timestamps Gemini wrote next to them.

Why match words and not lines: YouTube auto captions roll, so a sentence runs
across several lines and almost every line overlaps the next. In the stored
transcripts a sentence spans 2-4 lines, so a quote matched line by line would
almost never be found. The transcript is therefore flattened into one word
sequence, each word keeping the line it came from.

Why match loosely: two of the three stored transcripts carry essentially no
punctuation (0.0% and 0.2% of lines), auto captions mishear words, and Gemini
tends to tidy what it copies. Text is normalised (lowercase, punctuation
dropped) and compared as a ratio of words, so a quote survives a wrong word or
a missing one but a different sentence still fails.

A match is only trusted inside a window around the time Gemini gave. Outside
it, the quote is more likely a similar phrase from elsewhere in the video than
the one meant. `find_quote` searches the window; `find_quote_anywhere` searches
the whole transcript and is only used to tell three cases apart when measuring:
found where expected, found elsewhere (Gemini's timestamp drifted), and not
found at all (Gemini invented the quote).
"""
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import List, Optional, Sequence, Tuple

# Words of a quote compared at each end. A whole sentence is not needed to
# place it, and a long quote is likelier to have drifted from the transcript
# somewhere in the middle.
EDGE_WORDS = 8

# Share of words that must line up. Below this a match is a different
# sentence; the stored transcripts mishear roughly one word in ten, so a
# little slack is needed, and 0.7 keeps 2 of 8 words wrong acceptable.
MIN_SCORE = 0.7

# How far from Gemini's own timestamp a quote is still believed, in seconds.
# clip_bounds.MAX_SHIFT_SECONDS (8s) is the tested precedent for how far a
# clip edge may travel; this is a little wider because the quote is evidence
# in itself, and far narrower than the whole video.
WINDOW_SECONDS = 10.0

# Shortest quote worth trusting. Indonesian captions are full of filler
# ("ya ya ya", "oke oke"), which matches perfectly against other filler and
# would anchor a clip to nothing in particular.
MIN_NEEDLE_WORDS = 3

_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)


def normalize(text: object) -> str:
    """Lowercased text without punctuation or repeated spaces.

    Accents are kept: they distinguish words rather than decorate them.
    """
    if not isinstance(text, str):
        return ""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(_PUNCTUATION.sub(" ", folded).split())


def words_of(text: object) -> List[str]:
    """A quote as its normalised words."""
    return normalize(text).split()


@dataclass(frozen=True)
class Match:
    """Where a quote was found."""

    score: float
    # The matched words' first and last line, as indices into the transcript.
    first_line: int
    last_line: int
    # The spoken start of the first line and end of the last one.
    start: float
    end: float


class WordIndex:
    """A transcript as one word sequence, each word tied to its line.

    Lines keep the spoken end used elsewhere in the backend: a rolling line is
    spoken until the next one starts, so its end is min(its own end, the next
    line's start). Matching the whole sequence lets a quote cross lines.
    """

    def __init__(self, transcript: Sequence[dict]):
        # Sorted on the times only: falling through to the text would reorder
        # two lines sharing a timestamp alphabetically, scrambling the words.
        spans = sorted(
            ((float(l.get("start", 0.0)), float(l.get("end", 0.0)), str(l.get("text", "")))
             for l in transcript),
            key=lambda span: (span[0], span[1]),
        )
        self.starts: List[float] = [s for s, _, _ in spans]
        self.ends: List[float] = []
        for i, (s, e, _) in enumerate(spans):
            nxt = self.starts[i + 1] if i + 1 < len(spans) else None
            spoken = e if nxt is None or nxt <= s else min(e, nxt)
            self.ends.append(max(s, spoken))

        # Every word in order, and the line each one came from.
        self.words: List[str] = []
        self.line_of: List[int] = []
        for i, (_, _, text) in enumerate(spans):
            for word in words_of(text):
                self.words.append(word)
                self.line_of.append(i)

    def __len__(self) -> int:
        return len(self.words)

    def _line_range(self, lo: float, hi: float) -> Tuple[int, int]:
        """Word positions whose line overlaps [lo, hi]; empty as (0, 0)."""
        first = next((w for w, i in enumerate(self.line_of)
                      if self.ends[i] >= lo and self.starts[i] <= hi), None)
        if first is None:
            return 0, 0
        last = len(self.words)
        for w in range(len(self.words) - 1, first - 1, -1):
            if self.starts[self.line_of[w]] <= hi:
                last = w + 1
                break
        return first, last

    def _best_window(self, needle: Sequence[str], lo: int, hi: int) -> Optional[Match]:
        """The best place for `needle` among words [lo, hi), or None.

        Every window stays inside [lo, hi): reaching past it would score a
        quote against words outside the caller's search window, and anchor a
        clip to a sentence spoken minutes away.
        """
        n = len(needle)
        if n == 0 or hi - lo < MIN_NEEDLE_WORDS:
            return None
        best: Optional[Match] = None
        matcher = SequenceMatcher(autojunk=False)
        matcher.set_seq2(list(needle))
        # A window the length of the needle, slid one word at a time. Near the
        # end of the range the window is short rather than overrunning: a
        # quote may legitimately run past the range and still be scored on the
        # part that is inside it.
        for at in range(lo, hi):
            window = self.words[at:min(at + n, hi)]
            if len(window) < MIN_NEEDLE_WORDS:
                break
            matcher.set_seq1(window)
            # A cheap upper bound first: most windows share almost no words.
            if matcher.real_quick_ratio() < MIN_SCORE or matcher.quick_ratio() < MIN_SCORE:
                continue
            score = matcher.ratio()
            if best is not None and score <= best.score:
                continue
            last = at + len(window) - 1
            first_line, last_line = self.line_of[at], self.line_of[last]
            best = Match(
                score=round(score, 3),
                first_line=first_line,
                last_line=last_line,
                start=self.starts[first_line],
                end=self.ends[last_line],
            )
        return best if best is not None and best.score >= MIN_SCORE else None


def _edge(quote: object, *, tail: bool) -> List[str]:
    """The first or last EDGE_WORDS words of a quote, or [] if it is too short.

    A quote with fewer than MIN_NEEDLE_WORDS *distinct* words is rejected here
    rather than by each caller. Counting distinct words is what rules out
    filler like "ya ya ya", which is long enough but matches every other run
    of filler in the transcript just as well.
    """
    words = words_of(quote)
    if len(set(words)) < MIN_NEEDLE_WORDS:
        return []
    return words[-EDGE_WORDS:] if tail else words[:EDGE_WORDS]


def find_quote(
    quote: object,
    index: WordIndex,
    near: float,
    *,
    tail: bool = False,
    window: float = WINDOW_SECONDS,
) -> Optional[Match]:
    """Where a quote sits in the transcript, within `window` seconds of `near`.

    `tail=True` matches the quote's last words instead of its first, for the
    sentence a clip ends on. None when nothing in the window is close enough.
    """
    needle = _edge(quote, tail=tail)
    if not needle or len(index) == 0:
        return None
    lo, hi = index._line_range(near - window, near + window)
    return index._best_window(needle, lo, hi)


def find_quote_anywhere(quote: object, index: WordIndex, *, tail: bool = False) -> Optional[Match]:
    """Where a quote sits anywhere in the transcript, ignoring Gemini's time.

    Only for measuring (issue #99, stage 3): a quote found here but not by
    `find_quote` means Gemini's timestamp drifted, which is an argument for a
    wider window — not for abandoning the quotes.
    """
    needle = _edge(quote, tail=tail)
    if not needle or len(index) == 0:
        return None
    return index._best_window(needle, 0, len(index))
