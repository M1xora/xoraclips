"""
Caption text and chunking rules, shared by the render and the preview.

This module is the single source of truth for what a subtitle shows:
`generate_ass_file()` burns these chunks into the export and
`POST /api/caption-chunks` hands the same chunks to the browser preview.
Change a rule here and both follow.
"""
import logging
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger("xoraclips.video-engine")


@dataclass(frozen=True)
class ChunkRules:
    """
    Limits for grouping words into one on-screen caption.

    Defaults reproduce the renderer's behavior before these became
    parameters, so caption styles can override them individually later.
    """
    max_words: int = 3
    # Length of the chunk text, spaces included. The old packer was written
    # as "16" but miscounted spaces and in practice let every chunk after the
    # first reach 17; 17 keeps the output identical.
    max_chars: int = 17
    # A chunk stays on screen at least this long.
    min_chunk_duration: float = 0.25
    # Each word's highlight lasts at least this long inside its chunk.
    min_word_duration: float = 0.08


DEFAULT_RULES = ChunkRules()

# Tokens ending in one of these close a phrase, so a chunk ends after them.
_PHRASE_END = set(".,;:!?…。，、！？;")
_DASHES = set("-‐‑‒–—―")
_CLOSERS = set("\"'”’»)]}")
_APOSTROPHES = set("'’‘`´")
_HYPHENS = set("-‐‑")  # kept between letters/digits: anak-anak
# Kept between digits: 3,5  10.000  10.30  10:30  24/7
_NUMBER_SEPARATORS = set(".,:/")
_CURRENCY = set("$€£¥")  # kept right before a digit: $5
_MINUS = set("-−")  # kept as a sign right before a digit: -5

# A trailing "." on these does not end a phrase: "Mr. Smith", "Jl. Sudirman".
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "st", "jr", "sr", "vs", "no",
    "hlm", "yth", "sdr", "drs", "ir", "jl", "bpk", "rp",
}
# A currency word written apart from its amount ("Rp 10.000") is joined to it,
# so a chunk never shows "RP" on its own and the number in the next caption.
_CURRENCY_WORDS = {"rp", "idr"}
# A magnitude word after a number stays with it: "Rp1,5 juta" is one word.
_AMOUNT_UNITS = {"ribu", "rb", "juta", "jt", "miliar", "milyar", "triliun"}
# Indonesian price suffix ",-" ("Rp10.000,-") is part of the amount, not a dash.
_PRICE_SUFFIX = re.compile(r"\d,-$")
_DOTTED_ACRONYM = re.compile(r"^(?:[^\W\d_]\.){2,}$")  # U.S.  e.g.  a.m.

_TAG_RE = re.compile(r"\[.*?\]|\(.*?\)|\*.*?\*")


def strip_caption_tags(text: str) -> str:
    """Removes sound/action tags such as [Music], (Tertawa) and *cheering*."""
    return _TAG_RE.sub(" ", text or "")


def _is_word_char(ch: str) -> bool:
    # Letters, digits and combining marks (needed for many non-Latin scripts).
    return unicodedata.category(ch)[0] in ("L", "N", "M")


def clean_display_word(token: str) -> str:
    """
    Returns a token as it may appear on screen: every punctuation mark and
    symbol removed, except
      - a hyphen between two letters/digits: "anak-anak"
      - marks that are part of a number, so its meaning does not change:
        "3,5", "10.000", "10.30", "10:30", "24/7", "50%", "$5", "-5"
    Apostrophes are dropped so the word joins up: "don't" -> "dont".
    """
    t = unicodedata.normalize("NFC", token or "")
    t = "".join(ch for ch in t if ch not in _APOSTROPHES)
    out = []
    for i, ch in enumerate(t):
        prev = t[i - 1] if i > 0 else ""
        nxt = t[i + 1] if i + 1 < len(t) else ""
        if _is_word_char(ch):
            out.append(ch)
        elif ch in _HYPHENS and prev and nxt and _is_word_char(prev) and _is_word_char(nxt):
            out.append("-")
        elif ch in _NUMBER_SEPARATORS and prev.isdigit() and nxt.isdigit():
            out.append(ch)
        elif ch == "%" and prev.isdigit():
            out.append(ch)
        elif (ch in _CURRENCY or ch in _MINUS) and nxt.isdigit() and not (prev and _is_word_char(prev)):
            out.append("-" if ch in _MINUS else ch)
    return "".join(out)


def ends_phrase(token: str) -> bool:
    """
    True when the token closes a phrase: "lalu," "sendiri." "keduanya--".
    A full stop after an abbreviation ("Mr." "U.S." "Rp.") and the price
    suffix ",-" ("Rp10.000,-") do not count.
    """
    t = (token or "").rstrip()
    while t and t[-1] in _CLOSERS:
        t = t[:-1]
    if not t or _PRICE_SUFFIX.search(t):
        return False
    if t[-1] == ".":
        core = t.lstrip("\"'“‘«([{")
        if core[:-1].lower() in _ABBREVIATIONS or _DOTTED_ACRONYM.match(core):
            return False
    return t[-1] in _PHRASE_END or t[-1] in _DASHES


def tokenize_caption_text(text: str, break_at_end: bool = True) -> List[Dict[str, Any]]:
    """
    Splits caption text into display words, each flagged with `break_after`
    when a chunk must end after it: phrase punctuation, a standalone dash
    ("--", "—"), or (with `break_at_end`) the end of the caption line, so a
    chunk never spans two caption lines.
    """
    words: List[Dict[str, Any]] = []
    for token in strip_caption_tags(text).split():
        clean = clean_display_word(token)
        if not clean:
            # Punctuation-only tokens like "--" or "..." still mark a break.
            if words and ends_phrase(token):
                words[-1]["break_after"] = True
            continue
        prev = words[-1] if words else None
        if (
            prev is not None
            and prev["word"].lower() in _CURRENCY_WORDS
            and not prev["break_after"]
            and clean[0].isdigit()
        ):
            # "Rp 10.000" -> one word "Rp10.000", the usual written form.
            prev["word"] += clean
            prev["break_after"] = ends_phrase(token)
            continue
        if (
            prev is not None
            and clean.lower() in _AMOUNT_UNITS
            and not prev["break_after"]
            and any(ch.isdigit() for ch in prev["word"])
        ):
            # "1,5 juta" stays on one caption: never "RP1,5" then "JUTA".
            prev["word"] += " " + clean
            prev["break_after"] = ends_phrase(token)
            continue
        words.append({"word": clean, "break_after": ends_phrase(token)})
    if words and break_at_end:
        words[-1]["break_after"] = True
    return words


def _to_float(value: Any) -> Optional[float]:
    """A finite float, else None (NaN and inf are not times, issue #51)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _resolve_line_times(
    lines: List[Dict[str, Any]],
    clip_end_time: float = 0.0
) -> List[Dict[str, Any]]:
    """
    Normalizes transcript lines into sorted {text, start, end} entries.

    - `end` wins when present; legacy `duration` is still accepted.
    - Lines with neither (or an end not after start) are incomplete: they end
      at the next line's start, else the clip end, else start + 2s. This is
      always logged as a warning, never applied silently.
    - A line that runs past the start of the next later line is trimmed to
      it. YouTube auto captions overlap like this routinely.
    """
    parsed = []
    bad_start = []
    for line in lines:
        text = str(line.get("text") or "").strip()
        if not text:
            continue
        start = _to_float(line.get("start"))
        if start is None:
            if line.get("start") is not None:
                # Not a finite number ("", "abc", NaN, inf): no time to show it at (#51).
                bad_start.append(text)
                continue
            start = 0.0
        end = _to_float(line.get("end"))
        if end is None or end <= start:
            duration = _to_float(line.get("duration"))
            end = start + duration if duration is not None and duration > 0 else None
        parsed.append({"text": text, "start": start, "end": end})

    if bad_start:
        logger.warning(
            f"Skipped {len(bad_start)} transcript line(s) whose start is not a number. "
            f"Examples: {', '.join(repr(t[:30]) for t in bad_start[:3])}"
        )

    parsed.sort(key=lambda l: l["start"])

    # next_later[i]: start of the first following line that begins strictly
    # after line i. Lines sharing a start look past each other to it.
    next_later: List[Optional[float]] = [None] * len(parsed)
    for i in range(len(parsed) - 2, -1, -1):
        nxt = parsed[i + 1]["start"]
        next_later[i] = nxt if nxt > parsed[i]["start"] else next_later[i + 1]

    incomplete = []
    for i, line in enumerate(parsed):
        if line["end"] is not None:
            continue
        next_start = next_later[i]
        if next_start is not None:
            line["end"] = next_start
        elif clip_end_time > line["start"]:
            line["end"] = clip_end_time
        else:
            line["end"] = line["start"] + 2.0
        incomplete.append(line)

    if incomplete:
        sample = ", ".join(f"{l['start']:.2f}s '{l['text'][:30]}'" for l in incomplete[:3])
        logger.warning(
            f"Transcript has {len(incomplete)} line(s) without a usable end/duration; "
            f"end times were estimated. Examples: {sample}"
        )

    trimmed = 0
    for line, next_start in zip(parsed, next_later):
        if next_start is not None and line["end"] > next_start:
            line["end"] = next_start
            trimmed += 1
    if trimmed:
        # Routine for auto captions and logged on every preview request, so debug only.
        logger.debug(f"Trimmed {trimmed} overlapping transcript line(s) to the next line's start.")

    return parsed


def words_from_transcript(
    transcript: List[Dict[str, Any]],
    clip_start_time: float = 0.0,
    clip_end_time: float = 0.0
) -> List[Dict[str, Any]]:
    """
    Maps transcript lines to display words timed relative to the clip
    (0.0s = clip_start_time).

    Each line's words share the line's own time evenly, never running past
    its end, and only the words spoken inside the clip are kept: a word whose
    middle falls in [clip_start, clip_end) (issue #51). Before, every line
    ending up to 0.2s before the clip (the normal case: clips start at a line
    start and the previous line is trimmed to it) was squeezed into the first
    0.15s, so captions opened with words from the sentence before.

    With no clip (both times 0, the default) every line is kept at absolute
    times. A clip that ends at or before its start has no words.
    """
    has_clip = clip_start_time > 0 or clip_end_time > 0
    if has_clip and clip_end_time <= clip_start_time:
        return []
    origin = clip_start_time if has_clip else 0.0
    limit = clip_end_time - clip_start_time if has_clip else math.inf

    words = []
    for line in _resolve_line_times(transcript or [], clip_end_time):
        l_start = line["start"]
        l_end = line["end"]
        if has_clip and (l_end <= clip_start_time or l_start >= clip_end_time):
            continue

        # Tokenize only lines touching the clip: the preview asks on every trim.
        line_words = tokenize_caption_text(line["text"])
        if not line_words:
            continue

        # No minimum per word: a floor pushed the words of a fast line past
        # its end, where they overlapped the next line or fell outside the
        # clip. Readable timing is build_caption_chunks' job (min chunk length).
        step = (l_end - l_start) / len(line_words)
        kept = []
        for i, w in enumerate(line_words):
            w_s = l_start + i * step
            w_e = w_s + step
            if has_clip and not clip_start_time <= (w_s + w_e) / 2 < clip_end_time:
                continue
            kept.append({
                "word": w["word"],
                "start": round(max(0.0, w_s - origin), 2),
                "end": round(min(limit, w_e - origin), 2),
                "break_after": w["break_after"],
            })
        if kept:
            # A chunk never spans two caption lines, also when the clip cut
            # off the end of this one.
            kept[-1]["break_after"] = True
            words.extend(kept)
    return words


def apply_text_case(text: str, mode: str) -> str:
    """Applies uppercase, capitalize (Title Case), or lowercase to text."""
    clean = text.strip()
    if mode == "uppercase":
        return clean.upper()
    elif mode == "lowercase":
        return clean.lower()
    elif mode == "capitalize":
        return clean.title()
    return clean


def build_caption_chunks(
    words: List[Dict[str, Any]],
    text_case: str = "uppercase",
    rules: ChunkRules = DEFAULT_RULES
) -> List[Dict[str, Any]]:
    """
    Groups timed words into on-screen chunks.

    Returns [{start, end, text, words: [{text, start, end}]}]. Each word's
    start/end is the slice during which it is highlighted; slices tile the
    chunk exactly. Times keep the input's timebase (relative to the clip).
    """
    # Step A: Sanitize and sort all word timestamps
    valid_words = []
    for w in words:
        # A word may hold a space ("1,5 juta"); clean each part, keep the space.
        parts = (clean_display_word(p) for p in str(w.get("word", "")).split())
        raw_text = " ".join(p for p in parts if p)
        if not raw_text:
            continue
        w_text = apply_text_case(raw_text, text_case)
        st = max(0.0, float(w.get("start", 0.0)))
        et = max(st + rules.min_word_duration, float(w.get("end", st + 0.25)))
        valid_words.append({
            "word_text": w_text,
            "start": st,
            "end": et,
            "break_after": bool(w.get("break_after")),
        })

    valid_words.sort(key=lambda x: x["start"])

    # Step B: Pack into compact chunks. A chunk ends when it is full (word or
    # character limit, spaces included) or after a word flagged break_after.
    chunks: List[List[Dict[str, Any]]] = []
    current_chunk: List[Dict[str, Any]] = []
    current_chars = 0
    for item in valid_words:
        w_len = len(item["word_text"])
        if current_chunk and (
            len(current_chunk) >= rules.max_words
            or current_chars + 1 + w_len > rules.max_chars
        ):
            chunks.append(current_chunk)
            current_chunk, current_chars = [], 0
        current_chars += w_len + (1 if current_chunk else 0)
        current_chunk.append(item)
        if item["break_after"]:
            chunks.append(current_chunk)
            current_chunk, current_chars = [], 0
    if current_chunk:
        chunks.append(current_chunk)

    # Step C: Enforce strictly non-overlapping, monotonically increasing chunk boundaries
    chunk_bounds = []
    for chunk in chunks:
        c_start = chunk[0]["start"]
        c_end = max(c_start + rules.min_chunk_duration, chunk[-1]["end"])
        if chunk_bounds:
            prev_end = chunk_bounds[-1][1]
            if c_start < prev_end:
                c_start = prev_end
            if c_end <= c_start:
                c_end = c_start + rules.min_chunk_duration
        chunk_bounds.append((c_start, c_end))

    # Clamp against subsequent chunk start times to eliminate any inter-chunk overlaps
    for i in range(len(chunk_bounds) - 1):
        cur_s, cur_e = chunk_bounds[i]
        nxt_s, _ = chunk_bounds[i + 1]
        if cur_e > nxt_s:
            chunk_bounds[i] = (cur_s, nxt_s)

    # Step D: Partition each chunk into strictly contiguous active-word time slices
    result = []
    for chunk_idx, chunk in enumerate(chunks):
        c_start, c_end = chunk_bounds[chunk_idx]
        if c_end <= c_start:
            # Degenerate after clamping; keep the chunk visible briefly.
            c_end = c_start + 0.20
        num_words = len(chunk)

        if num_words == 1:
            time_slices = [(c_start, c_end)]
        else:
            points = [c_start]
            for w_i in range(1, num_words):
                raw_st = chunk[w_i]["start"]
                min_allowed = points[-1] + rules.min_word_duration
                max_allowed = c_end - rules.min_word_duration * (num_words - w_i)
                if min_allowed > max_allowed:
                    pt = points[-1] + (c_end - points[-1]) / (num_words - w_i + 1)
                else:
                    pt = max(min_allowed, min(max_allowed, raw_st))
                points.append(pt)
            points.append(c_end)
            time_slices = [(points[k], points[k + 1]) for k in range(num_words)]

        result.append({
            "start": c_start,
            "end": c_end,
            "text": " ".join(item["word_text"] for item in chunk),
            "words": [
                {"text": item["word_text"], "start": s, "end": e}
                for item, (s, e) in zip(chunk, time_slices)
            ],
        })
    return result


def caption_chunks_for_clip(
    transcript: List[Dict[str, Any]],
    clip_start: float,
    clip_end: float,
    text_case: str = "uppercase",
    rules: ChunkRules = DEFAULT_RULES
) -> List[Dict[str, Any]]:
    """The chunks a clip's export burns in, for the browser preview."""
    return build_caption_chunks(
        words_from_transcript(transcript, clip_start, clip_end), text_case, rules
    )
