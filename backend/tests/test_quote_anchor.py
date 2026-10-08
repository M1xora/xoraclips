"""
Issue #99: finding Gemini's quotes back in the transcript.

The lines here copy the shape of the stored transcripts rather than a tidy
invention: they roll (each line still on screen when the next starts), carry no
punctuation, and a sentence runs across several of them. Measured on
fixtures/transcripts: 0.0% and 0.2% of lines in two of the three hold a full
stop, and a sentence spans 2-4 lines.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend import quote_anchor  # noqa: E402
from backend.quote_anchor import WordIndex, find_quote, find_quote_anywhere, normalize, words_of  # noqa: E402


# Taken from fixtures/transcripts/kesehatan_YGjXfLsuG8k.json (lines 40-47),
# with the real rolling overlap: every line is still up when the next begins.
ROLLING = [
    {"start": 114.72, "end": 120.72, "text": "keluar mereka ditangkap karena diduga"},
    {"start": 117.76, "end": 123.96, "text": "ada bisnis cangkok ginjel"},
    {"start": 120.72, "end": 125.84, "text": "yang orangnya iku adalah yang pernah"},
    {"start": 123.96, "end": 129.00, "text": "transplan atau cangkok ginjal di luar"},
    {"start": 125.84, "end": 131.48, "text": "negeri Jadi mereka itu kayak sindikat"},
    {"start": 129.00, "end": 133.40, "text": "lah jual beli ginjal Emang kalau boleh"},
    {"start": 131.48, "end": 137.56, "text": "tahu satu ginjal Harganya berapa pak"},
    {"start": 133.40, "end": 140.60, "text": "aduh kira-kira ya 200 sampai"},
]


@pytest.fixture
def index():
    return WordIndex(ROLLING)


# --- normalising ----------------------------------------------------------------------

def test_normalize_drops_punctuation_and_case_but_keeps_accents():
    assert normalize("Emang, kalau BOLEH tahu?!") == "emang kalau boleh tahu"
    assert normalize("  dua   spasi  ") == "dua spasi"
    assert normalize("café") == "café"


def test_normalize_survives_what_gemini_might_send():
    for bad in (None, 123, [], {}):
        assert normalize(bad) == ""
    assert words_of("") == []


# --- finding a quote ------------------------------------------------------------------

def test_a_quote_copied_exactly_is_found(index):
    m = find_quote("Jadi mereka itu kayak sindikat lah jual beli ginjal", index, near=126.0)
    assert m is not None and m.score == 1.0
    # It starts inside the line that holds its first word.
    assert m.start == 125.84


def test_a_quote_running_across_lines_is_found(index):
    """No single line holds this sentence; the word sequence does."""
    quote = "negeri Jadi mereka itu kayak sindikat lah jual beli ginjal Emang kalau boleh tahu"
    m = find_quote(quote, index, near=127.0)
    # Only the first EDGE_WORDS words are matched, and they already cross a
    # line boundary — which a line-by-line match could never do.
    assert m is not None and m.last_line > m.first_line


def test_a_tidied_up_quote_is_still_found(index):
    """Gemini adds punctuation and fixes a typo; the clip must still anchor."""
    m = find_quote("Jadi, mereka itu kayak sindikat!", index, near=126.0)
    assert m is not None and m.score >= quote_anchor.MIN_SCORE
    # "ginjel" is a mishearing of "ginjal": one wrong word out of a short quote.
    m2 = find_quote("ada bisnis cangkok ginjal", index, near=118.0)
    assert m2 is not None


def test_a_sentence_that_is_not_in_the_transcript_is_not_found(index):
    assert find_quote("sama sekali tidak pernah diucapkan siapa pun", index, near=126.0) is None


def test_an_empty_or_missing_quote_is_not_found(index):
    for quote in ("", "   ", None, 42):
        assert find_quote(quote, index, near=126.0) is None


def test_an_empty_transcript_is_not_searched():
    assert find_quote("apa saja", WordIndex([]), near=0.0) is None
    assert find_quote_anywhere("apa saja", WordIndex([])) is None


# --- the window -----------------------------------------------------------------------

def test_a_quote_outside_the_window_is_not_trusted(index):
    quote = "Jadi mereka itu kayak sindikat"
    assert find_quote(quote, index, near=126.0) is not None
    # The same words, looked for a minute away: out of the window.
    assert find_quote(quote, index, near=300.0) is None


def test_searching_anywhere_tells_a_drifted_timestamp_from_an_invented_quote(index):
    """Issue #99 stage 3: the two must not be read as the same failure."""
    drifted = "Jadi mereka itu kayak sindikat"
    assert find_quote(drifted, index, near=300.0) is None
    assert find_quote_anywhere(drifted, index) is not None     # Gemini's time was wrong

    invented = "sama sekali tidak pernah diucapkan siapa pun"
    assert find_quote_anywhere(invented, index) is None        # Gemini made it up


# --- the end of a clip ----------------------------------------------------------------

def test_the_tail_of_a_quote_places_the_end_of_a_clip(index):
    m = find_quote("Emang kalau boleh tahu satu ginjal Harganya berapa pak", index,
                   near=133.0, tail=True)
    assert m is not None and m.score == 1.0
    # "pak" is the last word of the line starting at 131.48. Rolling captions
    # leave it on screen until 137.56, but it is only spoken until the next
    # line starts at 133.40 — the same spoken end clip_bounds uses.
    assert m.end == 133.40


def test_the_head_and_the_tail_of_one_quote_land_apart(index):
    quote = ("keluar mereka ditangkap karena diduga ada bisnis cangkok ginjel "
             "yang orangnya iku adalah yang pernah transplan atau cangkok ginjal di luar negeri")
    head = find_quote(quote, index, near=115.0)
    tail = find_quote(quote, index, near=126.0, tail=True)
    assert head is not None and tail is not None
    assert head.start < tail.end


# --- against the real transcripts -----------------------------------------------------

FIXTURES = Path(__file__).parent / "fixtures" / "transcripts"


@pytest.mark.parametrize("name", ["kesehatan_YGjXfLsuG8k", "komedi_qedBB492cQY", "debat_Mwmex7kDaaE"])
def test_a_quote_lifted_from_a_real_transcript_is_found(name):
    """The strongest case there is: the quote is the transcript's own words."""
    import json
    data = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    raw = data.get("transcript") or data.get("lines") or data
    lines = [{"start": l["start"], "end": l["start"] + l.get("duration", 0.0), "text": l["text"]}
             for l in raw]
    index = WordIndex(lines)

    # A quote the way Gemini would copy one: several consecutive lines joined.
    at = len(lines) // 2
    quote = " ".join(l["text"] for l in lines[at:at + 3])
    m = find_quote(quote, index, near=lines[at]["start"])
    assert m is not None, f"{name}: {quote!r}"
    assert m.score >= quote_anchor.MIN_SCORE
    assert abs(m.start - lines[at]["start"]) < quote_anchor.WINDOW_SECONDS
