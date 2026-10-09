"""
Issue #112: Whisper (automatic subtitles) is an optional install.

`openai-whisper` pulls torch, numba, llvmlite and sympy: ~737 MB of a
~1,029 MB install. It is only ever a fallback, for videos YouTube has no
transcript for, so it was moved to backend/requirements-whisper.txt.

These tests lock in what the rest of the app relies on when it is absent:

  - nothing raises; a missing Whisper degrades, it does not crash,
  - a clip from a video with no transcript still renders, just without
    subtitles,
  - a video that HAS a transcript never touches Whisper at all,
  - /api/health reports availability, so the Studio can say so rather than
    returning a subtitle-less clip with no explanation.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

import video_engine
from video_engine import transcribe_clip_words, whisper_available

LINES = [
    {"start": 10.0, "end": 12.0, "text": "satu dua"},
    {"start": 12.0, "end": 14.0, "text": "tiga empat"},
]

REQUIREMENTS = Path(__file__).resolve().parent.parent / "requirements.txt"
REQUIREMENTS_WHISPER = Path(__file__).resolve().parent.parent / "requirements-whisper.txt"


@pytest.fixture(autouse=True)
def reset_model_cache():
    """The model handle is a module global; keep tests from leaking into each other."""
    before = video_engine._WHISPER_MODEL
    video_engine._WHISPER_MODEL = None
    yield
    video_engine._WHISPER_MODEL = before


def test_get_whisper_model_returns_none_when_import_fails(monkeypatch):
    """A missing Whisper must degrade, never raise: the render depends on it.

    get_whisper_model() uses a bare `import whisper`, so a None in sys.modules
    is what makes the import fail; find_spec plays no part here.
    """
    monkeypatch.setitem(sys.modules, "whisper", None)

    assert video_engine.get_whisper_model() is None


def test_clip_without_transcript_renders_without_subtitles(monkeypatch):
    """No transcript and no Whisper: empty words, not an exception.

    generate_ass_file() takes an empty list and writes a subtitle-free file,
    so the clip still renders. That is the whole safety net for #112.
    """
    monkeypatch.setattr(video_engine, "get_whisper_model", lambda: None)

    words = transcribe_clip_words("unused.mp4", None, 10.0, 14.0)

    assert words == []


def test_transcript_is_used_without_touching_whisper(monkeypatch):
    """The primary path must never load the model: that is why it stays optional."""
    def fail(*args, **kwargs):
        raise AssertionError("Whisper was called even though a transcript exists")

    monkeypatch.setattr(video_engine, "get_whisper_model", fail)

    words = transcribe_clip_words("unused.mp4", LINES, 10.0, 14.0)

    assert [w["word"] for w in words] == ["satu", "dua", "tiga", "empat"]


def test_whisper_available_true_when_both_packages_present(monkeypatch):
    """The positive case: whisper AND torch resolve, so subtitles can run."""
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name, *a, **k: object()
    )

    assert whisper_available() is True


def test_whisper_available_false_when_torch_is_missing(monkeypatch):
    """Caught in review: whisper/ can outlive torch once #112 drops it.

    find_spec("whisper") succeeds without executing the package, but
    whisper/__init__.py imports torch at module level and fails on first use.
    Calling that available would hide the Studio warning and hand the user a
    subtitle-less clip with no explanation.
    """
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a, **k: None if name == "torch" else object(),
    )

    assert whisper_available() is False


def test_whisper_available_does_not_load_the_model(monkeypatch):
    """A status check must stay cheap: loading the model costs seconds and RAM."""
    def fail():
        raise AssertionError("whisper_available() loaded the model")

    monkeypatch.setattr(video_engine, "get_whisper_model", fail)
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name, *a, **k: object()
    )

    assert whisper_available() is True


def test_whisper_available_ignores_a_failed_load(monkeypatch):
    """A dropped model download must not become "go install Whisper".

    _WHISPER_MODEL is False after ANY load failure, including a network drop
    mid-download. Someone who has Whisper installed would then be told to
    install it, which is worse than one wasted retry.
    """
    video_engine._WHISPER_MODEL = False
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name, *a, **k: object()
    )

    assert whisper_available() is True


def test_whisper_available_false_when_module_missing(monkeypatch):
    real_find_spec = importlib.util.find_spec

    def no_whisper(name, *args, **kwargs):
        return None if name == "whisper" else real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", no_whisper)

    assert whisper_available() is False


def test_whisper_available_survives_a_broken_install(monkeypatch):
    """find_spec() raises on a half-broken package; /api/health must not 500.

    Caught in review: an import hook that rejects `whisper` made find_spec()
    raise, which took the health endpoint down with it.
    """
    def boom(name, *args, **kwargs):
        raise ImportError("broken install")

    monkeypatch.setattr(importlib.util, "find_spec", boom)

    assert whisper_available() is False


def test_health_reports_whisper_availability():
    """The frontend reads this to decide whether to warn (#112)."""
    from fastapi.testclient import TestClient
    from main import app

    body = TestClient(app).get("/api/health").json()

    assert "whisper_available" in body
    assert isinstance(body["whisper_available"], bool)


def test_requirements_no_longer_install_whisper():
    """The 737 MB saving is the point of the issue; keep it from creeping back."""
    text = REQUIREMENTS.read_text(encoding="utf-8")
    installed = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    assert not any("whisper" in line.lower() for line in installed)
    assert not any(line.lower().startswith("torch") for line in installed)


def test_optional_requirements_file_installs_whisper():
    text = REQUIREMENTS_WHISPER.read_text(encoding="utf-8")
    installed = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    assert any("openai-whisper" in line for line in installed)
    assert any(line.lower().startswith("torch") for line in installed)
