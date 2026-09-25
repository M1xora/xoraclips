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
    words_from_transcript,
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


# --- Rupiah amounts (no YouTube needed) ------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("Rp10.000", "Rp10.000"),
    ("Rp.10.000", "Rp10.000"),
    ("Rp10.000,-", "Rp10.000"),
    ("Rp10.000,00", "Rp10.000,00"),
    ("Rp1.500.000,00", "Rp1.500.000,00"),
    ("Rp1,5", "Rp1,5"),
    ("Rp50rb", "Rp50rb"),
    ("Rp2,5M", "Rp2,5M"),
    ("(Rp25.000)", "Rp25.000"),
    ("Rp10.000.", "Rp10.000"),
    ("50.000,", "50.000"),
    ("IDR", "IDR"),
])
def test_rupiah_amounts_keep_their_digits_and_separators(raw, expected):
    assert clean_display_word(raw) == expected


@pytest.mark.parametrize("token, breaks", [
    ("Rp10.000", False),
    ("10.000", False),       # the "." inside a number is not a full stop
    ("Rp10.000,-", False),   # ",-" is the price suffix, not a dash
    ("Rp.", False),          # abbreviation
    ("Rp10.000,", True),
    ("Rp10.000.", True),
    ("rupiah!", True),
])
def test_rupiah_break_points(token, breaks):
    from captions import ends_phrase
    assert ends_phrase(token) is breaks


@pytest.mark.parametrize("text, expected", [
    ("harga Rp 10.000 saja", ["harga", "Rp10.000", "saja"]),
    ("harga Rp. 10.000 saja", ["harga", "Rp10.000", "saja"]),
    ("IDR 50.000 per bulan", ["IDR50.000", "per", "bulan"]),
    ("hemat Rp 500.000,- sebulan", ["hemat", "Rp500.000", "sebulan"]),
    # Not followed by a number: stays a word of its own.
    ("bayar pakai Rp saja", ["bayar", "pakai", "Rp", "saja"]),
])
def test_currency_word_joins_its_amount(text, expected):
    assert [w["word"] for w in tokenize_caption_text(text)] == expected


def test_rupiah_is_never_split_from_its_amount_across_chunks():
    lines = [{
        "start": 0.0, "end": 8.0,
        "text": "Harganya Rp 1.500.000,00 per bulan. Diskon jadi Rp1,5 juta, hemat Rp.500.000,- lho",
    }]
    for text_case in ["uppercase", "capitalize", "lowercase"]:
        chunks = caption_chunks_for_clip(lines, 0.0, 8.0, text_case)
        words = [w["text"] for c in chunks for w in c["words"]]
        assert all(re.fullmatch(r"(?i)rp", w) is None for w in words), words
        for w in words:
            assert all(ALLOWED_WORD.match(part) for part in w.split(" ")), w
    assert [c["text"] for c in caption_chunks_for_clip(lines, 0.0, 8.0)] == [
        "HARGANYA", "RP1.500.000,00", "PER BULAN", "DISKON JADI", "RP1,5 JUTA", "HEMAT RP500.000", "LHO",
    ]


@pytest.mark.parametrize("text, expected", [
    ("gajinya 10 juta, rumah 2 miliar", ["gajinya", "10 juta", "rumah", "2 miliar"]),
    ("Rp 50 rb saja", ["Rp50 rb", "saja"]),
    ("naik 3 persen", ["naik", "3", "persen"]),      # not an amount unit
    ("umur 10. Juta orang", ["umur", "10", "Juta", "orang"]),  # sentence ended
])
def test_amount_stays_with_its_unit(text, expected):
    assert [w["word"] for w in tokenize_caption_text(text)] == expected


# --- Clip edges (issue #51) --------------------------------------------------
# Clips start at a line start and the line before is trimmed to end there, so
# "ends exactly at the clip start" is the normal case, not an edge case.

EDGE_LINES = [
    {"start": 5.0, "end": 10.0, "text": "kalimat sebelumnya"},
    {"start": 10.0, "end": 14.0, "text": "awal klip ini"},
    {"start": 14.0, "end": 18.0, "text": "sesudah klip"},
]


def _chunk_texts(lines, start, end):
    return [c["text"] for c in caption_chunks_for_clip(lines, start, end, "uppercase")]


def test_lines_touching_the_clip_edges_stay_out():
    # Before #51: KALIMAT AWAL / SEBELUMNYA / KLIP INI / SESUDAH KLIP (4.0-8.0s).
    assert _chunk_texts(EDGE_LINES, 10.0, 14.0) == ["AWAL KLIP INI"]


def test_overlapping_auto_captions_do_not_leak_into_the_clip():
    # YouTube auto captions roll: each line runs past the next one's start.
    rolling = [
        {"start": 15.08, "duration": 4.16, "text": "yang namanya sehat itu susah kalau sakit"},
        {"start": 17.28, "duration": 4.44, "text": "mah gampang gitu kita tinggal keluar"},
        {"start": 19.24, "duration": 4.0, "text": "rumah langsung ketemu"},
    ]
    text = " ".join(_chunk_texts(rolling, 17.28, 19.24))
    assert text == "MAH GAMPANG GITU KITA TINGGAL KELUAR"


def test_a_line_cut_by_the_clip_start_keeps_only_the_words_inside():
    lines = [{"start": 0.0, "end": 4.0, "text": "satu dua tiga empat"}]
    # Words at 0-1, 1-2, 2-3, 3-4: middles 0.5, 1.5, 2.5, 3.5.
    words = words_from_transcript(lines, 2.0, 10.0)
    assert [w["word"] for w in words] == ["tiga", "empat"]
    assert words[0]["start"] == 0.0


def test_a_line_cut_by_the_clip_end_keeps_only_the_words_inside():
    lines = [{"start": 0.0, "end": 4.0, "text": "satu dua tiga empat"}]
    words = words_from_transcript(lines, 0.0, 2.0)
    assert [w["word"] for w in words] == ["satu", "dua"]
    # The clip cut the line: its last kept word still ends a chunk.
    assert words[-1]["break_after"] is True


def test_every_word_time_is_inside_the_clip():
    lines = [
        {"start": 0.0, "end": 6.0, "text": "a b c d e f g h i j"},
        {"start": 6.0, "end": 9.0, "text": "k l m n o p"},
    ]
    start, end = 2.3, 7.7
    for w in words_from_transcript(lines, start, end):
        assert 0.0 <= w["start"] < w["end"] <= round(end - start, 2)


def test_a_clip_that_ends_at_or_before_its_start_has_no_words():
    assert words_from_transcript(EDGE_LINES, 14.0, 14.0) == []
    assert words_from_transcript(EDGE_LINES, 14.0, 10.0) == []
    assert caption_chunks_for_clip(EDGE_LINES, 100.0, 100.0, "uppercase") == []


def test_without_a_clip_all_lines_keep_absolute_times():
    words = words_from_transcript(EDGE_LINES)
    assert words[0]["word"] == "kalimat" and words[0]["start"] == 5.0
    assert words[-1]["word"] == "klip"


@pytest.mark.parametrize("bad", ["nan", float("nan"), "inf", float("-inf")])
def test_a_line_whose_start_is_not_a_finite_number_is_ignored(bad):
    lines = [{"start": bad, "end": 3.0, "text": "rusak"}] + EDGE_LINES
    assert "RUSAK" not in " ".join(_chunk_texts(lines, 0.0, 12.0))


# A fast line: 8 words in 0.5s. Found by /code-review: with a 0.12s floor per
# word the last words ran past the line and fell outside a clip ending there.
FAST_LINES = [
    {"start": 10.0, "end": 10.5, "text": "satu dua tiga empat lima enam tujuh delapan"},
    {"start": 10.5, "end": 12.0, "text": "sembilan sepuluh"},
]


def test_a_fast_line_keeps_all_its_words_when_the_clip_ends_with_it():
    words = words_from_transcript(FAST_LINES, 9.0, 10.5)
    assert [w["word"] for w in words] == "satu dua tiga empat lima enam tujuh delapan".split()


def test_words_stay_in_order_and_inside_their_line():
    words = words_from_transcript(FAST_LINES, 9.0, 20.0)
    starts = [w["start"] for w in words]
    assert starts == sorted(starts)
    delapan = next(w for w in words if w["word"] == "delapan")
    sembilan = next(w for w in words if w["word"] == "sembilan")
    assert delapan["end"] <= sembilan["start"]


def test_a_clip_with_a_start_but_no_end_has_no_words():
    # Not "no clip": absolute times would put the words past the clip.
    assert words_from_transcript(EDGE_LINES, 12.0, 0.0) == []


def test_a_start_that_is_not_a_number_is_skipped_and_logged(caplog):
    lines = [{"start": "abc", "end": 3.0, "text": "rusak"}, {"start": "", "end": 3.0, "text": "kosong"}]
    with caplog.at_level("WARNING"):
        assert words_from_transcript(lines + EDGE_LINES, 0.0, 12.0)[0]["word"] == "kalimat"
    assert "Skipped 2 transcript line(s) whose start is not a number" in caplog.text
