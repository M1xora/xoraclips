"""
Regression tests for issue #4: subtitle timing in rendered clips.

The frontend sends transcript lines as {start, end, text} with no `duration`.
The renderer used to read `duration` with a silent 2.0s default, so every
line was treated as two seconds long and captions drifted off the audio.
"""
import logging

import pytest

import video_engine
from video_engine import transcribe_clip_words

LOGGER_NAME = "xoraclips.video-engine"

# The simulation from the issue: a 4s line, a 1s line, then a 4s line,
# inside a clip that runs from 10s to 19s of the source video.
CLIP_START = 10.0
CLIP_END = 19.0

LINES_START_END = [
    {"start": 10.0, "end": 14.0, "text": "satu dua tiga empat"},
    {"start": 14.0, "end": 15.0, "text": "lima enam"},
    {"start": 15.0, "end": 19.0, "text": "tujuh delapan"},
]

LINES_LEGACY_DURATION = [
    {"start": 10.0, "duration": 4.0, "text": "satu dua tiga empat"},
    {"start": 14.0, "duration": 1.0, "text": "lima enam"},
    {"start": 15.0, "duration": 4.0, "text": "tujuh delapan"},
]

EXPECTED = [
    ("satu", 0.0, 1.0),
    ("dua", 1.0, 2.0),
    ("tiga", 2.0, 3.0),
    ("empat", 3.0, 4.0),
    ("lima", 4.0, 4.5),
    ("enam", 4.5, 5.0),
    ("tujuh", 5.0, 7.0),
    ("delapan", 7.0, 9.0),
]


@pytest.fixture(autouse=True)
def no_whisper(monkeypatch):
    """A transcript is always supplied here, so Whisper must never load."""
    def fail():
        raise AssertionError("Whisper must not be used when a transcript is available")
    monkeypatch.setattr(video_engine, "get_whisper_model", fail)


def as_tuples(words):
    return [(w["word"], w["start"], w["end"]) for w in words]


def assert_ordered_without_overlap(words, expected_text):
    assert [w["word"] for w in words] == expected_text.split()
    for prev, cur in zip(words, words[1:]):
        assert cur["start"] >= prev["end"], f"{prev} overlaps {cur}"


def test_uses_end_minus_start_when_end_is_present():
    words = transcribe_clip_words("unused.mp4", LINES_START_END, CLIP_START, CLIP_END)
    assert as_tuples(words) == EXPECTED


def test_still_supports_legacy_duration_field():
    words = transcribe_clip_words("unused.mp4", LINES_LEGACY_DURATION, CLIP_START, CLIP_END)
    assert as_tuples(words) == EXPECTED


@pytest.mark.parametrize("fmt", ["end", "duration"])
def test_overlapping_auto_caption_lines_are_trimmed(fmt):
    # YouTube auto captions: each line is still "on screen" when the next starts.
    raw = [
        (0.0, 3.5, "halo semua selamat datang"),
        (2.0, 5.0, "di channel saya"),
        (4.1, 7.0, "hari ini kita"),
    ]
    lines = [
        {"start": s, "text": t, **({"end": e} if fmt == "end" else {"duration": e - s})}
        for s, e, t in raw
    ]

    words = transcribe_clip_words("unused.mp4", lines, 0.0, 7.0)

    assert_ordered_without_overlap(words, " ".join(t for _, _, t in raw))
    # Each line now ends exactly where the next one begins.
    assert words[3]["end"] == pytest.approx(2.0)
    assert words[6]["end"] == pytest.approx(4.1)
    assert words[-1]["end"] == pytest.approx(7.0)


def test_line_sharing_a_start_is_trimmed_to_next_later_line():
    # A and B start together (e.g. a cue split into two entries); A must still
    # stop where C begins instead of running over it.
    lines = [
        {"start": 10.0, "end": 14.0, "text": "a b"},
        {"start": 10.0, "end": 11.0, "text": "c"},
        {"start": 12.0, "end": 13.0, "text": "d"},
    ]
    words = {w["word"]: w for w in transcribe_clip_words("unused.mp4", lines, 10.0, 14.0)}

    assert (words["a"]["start"], words["a"]["end"]) == (0.0, 1.0)
    assert (words["b"]["start"], words["b"]["end"]) == (1.0, 2.0)
    assert (words["d"]["start"], words["d"]["end"]) == (2.0, 3.0)


def test_incomplete_line_uses_next_start_and_logs_warning(caplog):
    lines = [
        {"start": 10.0, "text": "tanpa akhir"},
        {"start": 12.0, "end": 14.0, "text": "baris normal"},
    ]
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        words = transcribe_clip_words("unused.mp4", lines, 10.0, 14.0)

    assert as_tuples(words) == [
        ("tanpa", 0.0, 1.0),
        ("akhir", 1.0, 2.0),
        ("baris", 2.0, 3.0),
        ("normal", 3.0, 4.0),
    ]
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_incomplete_last_line_uses_clip_end_and_logs_warning(caplog):
    lines = [
        {"start": 10.0, "end": 12.0, "text": "x y"},
        {"start": 12.0, "end": 12.0, "text": "z"},  # end not after start: invalid
    ]
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        words = transcribe_clip_words("unused.mp4", lines, 10.0, 15.0)

    assert words[-1]["word"] == "z"
    assert (words[-1]["start"], words[-1]["end"]) == (2.0, 5.0)
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_complete_data_logs_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        transcribe_clip_words("unused.mp4", LINES_START_END, CLIP_START, CLIP_END)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
