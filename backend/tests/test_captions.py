"""
Tests for issue #6: one set of caption rules for the preview and the render.
"""
import json
import re
from pathlib import Path

import pytest

import captions
import video_engine
from captions import (
    ChunkRules,
    build_caption_chunks,
    caption_chunks_for_clip,
    clean_display_word,
    tokenize_caption_text,
)

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "ted_manual_captions.json").read_text(encoding="utf-8")
)

# What may remain after cleaning: letters/digits, a hyphen between word
# characters, and marks that belong to a number (3,5 10:30 24/7 50% $5 -5).
ALLOWED_WORD = re.compile(
    r"^(?:[$€£¥-](?=\d))?"
    r"(?:[^\W_]|(?<=[^\W_])-(?=[^\W_])|(?<=\d)[.,:/](?=\d)|(?<=\d)%)+$"
)


@pytest.mark.parametrize("raw, expected", [
    ("lalu,", "lalu"),
    ("sendiri.", "sendiri"),
    ("Serius?!", "Serius"),
    ("tunggu...", "tunggu"),
    ("kata;", "kata"),
    ("catatan:", "catatan"),
    ('"kutipan"', "kutipan"),
    ("“kutipan”", "kutipan"),
    ("(halo)", "halo"),
    ("don't", "dont"),
    ("that’s", "thats"),
    ("40�", "40"),
    ("--", ""),
    ("♪", ""),
    ("#tag", "tag"),
    ("a&b", "ab"),
    # Approved exceptions
    ("anak-anak", "anak-anak"),
    ("sehari-hari,", "sehari-hari"),
    ("3,5", "3,5"),
    ("10.000", "10.000"),
    ("10.30.", "10.30"),
    ("50%", "50%"),
    ("50%.", "50%"),
    ("Rp10.000,", "Rp10.000"),
    ("10:30", "10:30"),
    ("24/7,", "24/7"),
    ("1/2", "1/2"),
    ("$5", "$5"),
    ("($5)", "$5"),
    ("-5", "-5"),
    ("20-30", "20-30"),
    # Symbols that are not part of a number still go
    ("Q&A", "QA"),
    ("dan/atau", "danatau"),
    ("jam:", "jam"),
    ("$", ""),
    ("-", ""),
])
def test_clean_display_word(raw, expected):
    assert clean_display_word(raw) == expected


def test_tags_are_removed_but_ordinary_words_stay():
    words = [w["word"] for w in tokenize_caption_text("[Music] I love music (Tertawa) *cheering* yes")]
    assert words == ["I", "love", "music", "yes"]


def test_punctuation_marks_break_points():
    words = tokenize_caption_text("Beberapa tahun lalu, saya mendobrak -- masuk rumah sendiri. Lalu")
    breaks = [w["word"] for w in words if w["break_after"]]
    # comma, standalone dash, full stop, and the end of the caption line
    assert breaks == ["lalu", "mendobrak", "sendiri", "Lalu"]


def test_abbreviations_do_not_end_a_phrase():
    chunks = caption_chunks_for_clip(
        [{"start": 0.0, "end": 4.0, "text": "Mr. Smith went to the U.S. today"}], 0.0, 4.0
    )
    assert [c["text"] for c in chunks] == ["MR SMITH WENT", "TO THE US", "TODAY"]
    words = tokenize_caption_text("Kata Dr. Budi di Jl. Sudirman, e.g. besok.")
    assert [w["word"] for w in words if w["break_after"]] == ["Sudirman", "besok"]


def test_chunk_never_crosses_a_punctuation_break():
    chunks = caption_chunks_for_clip(
        [{"start": 0.0, "end": 4.0, "text": "ya, saya pergi. oke kita mulai"}], 0.0, 4.0
    )
    assert [c["text"] for c in chunks] == ["YA", "SAYA PERGI", "OKE KITA MULAI"]


def test_chunk_never_crosses_two_caption_lines():
    # Auto captions have no punctuation; the line boundary is the break.
    lines = [
        {"start": 0.0, "end": 2.0, "text": "halo semua"},
        {"start": 2.0, "end": 4.0, "text": "apa kabar hari ini"},
    ]
    assert [c["text"] for c in caption_chunks_for_clip(lines, 0.0, 4.0)] == [
        "HALO SEMUA", "APA KABAR HARI", "INI",
    ]


def test_default_rules_match_previous_limits():
    assert ChunkRules() == ChunkRules(max_words=3, max_chars=17, min_chunk_duration=0.25, min_word_duration=0.08)


def test_rules_are_parameters():
    words = [{"word": w, "start": i * 0.5, "end": (i + 1) * 0.5} for i, w in enumerate("satu dua tiga empat lima".split())]

    default = [c["text"] for c in build_caption_chunks(words)]
    two_words = [c["text"] for c in build_caption_chunks(words, rules=ChunkRules(max_words=2))]
    short = [c["text"] for c in build_caption_chunks(words, rules=ChunkRules(max_chars=9))]

    assert default == ["SATU DUA TIGA", "EMPAT LIMA"]
    assert two_words == ["SATU DUA", "TIGA EMPAT", "LIMA"]
    assert short == ["SATU DUA", "TIGA", "EMPAT", "LIMA"]


def test_min_chunk_duration_is_a_parameter():
    words = [{"word": "cepat", "start": 1.0, "end": 1.05}]
    assert build_caption_chunks(words)[0]["end"] == pytest.approx(1.25)
    assert build_caption_chunks(words, rules=ChunkRules(min_chunk_duration=0.6))[0]["end"] == pytest.approx(1.6)


def test_word_slices_tile_each_chunk():
    chunks = caption_chunks_for_clip(FIXTURE["id"], 13.2, 60.0)
    for c in chunks:
        assert c["words"][0]["start"] == pytest.approx(c["start"])
        assert c["words"][-1]["end"] == pytest.approx(c["end"])
        for a, b in zip(c["words"], c["words"][1:]):
            assert a["end"] == pytest.approx(b["start"])
    for a, b in zip(chunks, chunks[1:]):
        assert b["start"] >= a["end"] - 1e-9


@pytest.mark.parametrize("lang", ["id", "en"])
@pytest.mark.parametrize("text_case", ["uppercase", "capitalize", "lowercase"])
def test_real_captions_show_no_punctuation(lang, text_case):
    lines = FIXTURE[lang]
    chunks = caption_chunks_for_clip(lines, 0.0, lines[-1]["end"], text_case)
    assert chunks
    for c in chunks:
        for w in c["words"]:
            assert ALLOWED_WORD.match(w["text"]), f"{w['text']!r} in {c['text']!r}"


def _ass_chunks(ass_text):
    """Chunk text and word slices as burned into the .ass file."""
    chunks, current = [], None
    for line in ass_text.splitlines():
        if not line.startswith("Dialogue: 0,"):
            continue
        fields = line.split(",", 9)
        text = re.sub(r"\{[^}]*\}", "", fields[9])
        if current is None or current["text"] != text or fields[1] != current["last_end"]:
            current = {"text": text, "slices": [], "last_end": None}
            chunks.append(current)
        current["slices"].append((fields[1], fields[2]))
        current["last_end"] = fields[2]
    return [(c["text"], c["slices"]) for c in chunks]


@pytest.mark.parametrize("lang, clip", [("id", (13.2, 45.0)), ("en", (20.0, 70.0))])
def test_render_burns_exactly_the_preview_chunks(tmp_path, lang, clip):
    """The .ass file and /api/caption-chunks come from the same words and rules."""
    start, end = clip
    lines = FIXTURE[lang]
    words = video_engine.transcribe_clip_words("unused.mp4", lines, start, end)
    ass_path = video_engine.generate_ass_file(
        words, "viral_pop", "Outfit", str(tmp_path / "clip.ass"), title_position="none"
    )

    preview = caption_chunks_for_clip(lines, start, end, "uppercase")
    fmt = video_engine.format_ass_timestamp
    expected = [
        (c["text"], [(fmt(w["start"]), fmt(w["end"])) for w in c["words"] if w["end"] > w["start"]])
        for c in preview
    ]

    assert _ass_chunks(Path(ass_path).read_text(encoding="utf-8")) == expected


def test_render_module_uses_the_shared_rules():
    # Guard against a second copy of the rules creeping back into the renderer.
    # Compared by source file: the module may be imported as both
    # `captions` and `backend.captions`.
    code = video_engine.build_caption_chunks.__code__
    assert code.co_filename == captions.build_caption_chunks.__code__.co_filename
    assert not hasattr(video_engine, "clean_caption_text")


def test_frontend_fixture_matches_backend_output():
    """The preview's tests use real backend output; fail if it goes stale."""
    path = Path(__file__).resolve().parents[2] / "src-next" / "features" / "studio" / "__fixtures__" / "caption-chunks.ted.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    current = caption_chunks_for_clip(
        FIXTURE["id"], fixture["clip_start"], fixture["clip_end"], fixture["text_case"]
    )
    assert fixture["chunks"] == current
