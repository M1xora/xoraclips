"""
Issue #31: hook titles. Gemini's title options are checked one by one against
title_rules; broken ones are logged and dropped, and a safe fallback keeps
every clip usable. Gemini and YouTube are fakes: nothing here goes online.
"""
import importlib
import json
import logging

import pytest
from fastapi.testclient import TestClient

import main
import title_rules
from title_rules import GENERIC_FALLBACK, pick_titles, prompt_rules, title_problem

GOOD = [
    "dr. Tirta: Olahraga Berat Bisa Rusak Jantung?",
    "Ternyata Lari Tiap Hari Nggak Selalu Sehat",
    "Host Nggak Nyangka Jawaban Tamunya Begini",
]


# --- the rules ----------------------------------------------------------------------

@pytest.mark.parametrize("title", GOOD)
def test_good_titles_pass(title):
    assert title_problem(title) is None


@pytest.mark.parametrize("title, reason", [
    ("", "empty"),
    ("Ini Adalah Judul Yang Punya Delapan Kata Panjang", "8 words"),
    ("Kenapa Pertanggungjawaban Itu Penting Banget", "word"),
    ("Satu Studio Langsung Diam Dengar Jawaban Ini!!", "characters"),
    ("Ternyata Lari Tiap Hari #sehat", "hashtag"),
    ("Ternyata Lari Tiap Hari 🔥", "emoji"),
    ("Kenapa Saya Berhenti Lari Tiap Hari", "first person"),
])
def test_rule_breaks_are_named(title, reason):
    assert reason in (title_problem(title) or "")


def test_the_limits_are_settings_not_numbers_in_the_logic(monkeypatch):
    monkeypatch.setenv("XORACLIPS_MAX_TITLE_WORDS", "5")
    reloaded = importlib.reload(title_rules)
    try:
        assert reloaded.MAX_TITLE_WORDS == 5
        assert "at most 5 words" in reloaded.prompt_rules()
        assert "6 words" in reloaded.title_problem("Satu Dua Tiga Empat Lima Enam")
    finally:
        monkeypatch.delenv("XORACLIPS_MAX_TITLE_WORDS")
        importlib.reload(title_rules)


def test_the_prompt_carries_the_settings_and_the_rules():
    text = prompt_rules()
    assert f"exactly {title_rules.TITLE_OPTIONS} options" in text
    assert f"at most {title_rules.MAX_TITLE_WORDS} words" in text
    assert f"{title_rules.MAX_TITLE_CHARS} characters" in text
    assert "Indonesian" in text and "first 3-5 seconds" in text and "news headline" in text


# --- picking the titles ---------------------------------------------------------------

def test_three_good_options_are_kept_in_order():
    titles, problems = pick_titles([{"text": t, "angle": "x"} for t in GOOD])
    assert titles == GOOD and problems == []


def test_broken_options_are_dropped_and_logged(caplog):
    options = [
        {"text": "Ini Adalah Judul Yang Punya Delapan Kata Panjang"},
        {"text": "  \"Ternyata Lari Tiap Hari\n Nggak Selalu Sehat\"  "},  # cleaned, kept
        {"text": None},
        {"text": "ternyata lari tiap hari nggak selalu sehat"},  # duplicate
        "Host Nggak Nyangka Jawaban Tamunya Begini",  # plain string still read
    ]
    with caplog.at_level(logging.WARNING, logger="xoraclips.titles"):
        titles, problems = pick_titles(options, label="clip 1")
    assert titles == ["Ternyata Lari Tiap Hari Nggak Selalu Sehat", "Host Nggak Nyangka Jawaban Tamunya Begini"]
    assert len(problems) == 3
    assert "8 words" in caplog.text and "empty" in caplog.text and "duplicate" in caplog.text
    assert "clip 1" in caplog.text


def test_more_than_three_options_keeps_three():
    titles, problems = pick_titles(GOOD + ["Satu Studio Langsung Diam Dengar Ini"])
    assert titles == GOOD
    assert "extra option 4 ignored" in problems[0]


def test_no_options_falls_back_to_the_old_title_fields():
    titles, problems = pick_titles(None, legacy_title="Old Title Here", legacy_suggestion="Lari Tiap Hari Nggak Selalu Sehat")
    assert titles == ["Lari Tiap Hari Nggak Selalu Sehat"]
    assert "no title options" in problems[0]


def test_an_old_title_that_is_too_long_is_shortened_as_a_last_resort():
    long_old = "Dr. Tirta Jelaskan Bahaya Memaksa Jantung Bekerja Terlalu Keras Saat Olahraga"
    titles, problems = pick_titles([], legacy_title=long_old)
    # 7 words would be 49 characters, over the 45 limit: one more word goes.
    assert titles == ["Dr. Tirta Jelaskan Bahaya Memaksa Jantung"]
    assert title_problem(titles[0]) is None
    assert any("shortened" in p for p in problems)


def test_nothing_usable_gives_the_generic_title():
    titles, _ = pick_titles("not a list", legacy_title="", legacy_suggestion="")
    assert titles == [GENERIC_FALLBACK]
    assert title_problem(GENERIC_FALLBACK) is None


def test_the_first_person_fixer_still_runs_first():
    fixed = lambda t: t.replace("Saya", "dr. Tirta")  # stands in for sanitize_first_person_title
    titles, _ = pick_titles(["Saya Berhenti Lari Tiap Hari"], sanitize=fixed)
    assert titles == ["dr. Tirta Berhenti Lari Tiap Hari"]


# --- through /api/analyze ---------------------------------------------------------------

class Answer:
    parsed = None

    def __init__(self, payload):
        self.text = json.dumps(payload)


class FakeGemini:
    payload = None
    prompts = []

    def __init__(self, *args, **kwargs):
        self.models = self

    def list(self, *args, **kwargs):
        return []

    def generate_content(self, *args, model=None, contents=None, **kwargs):
        FakeGemini.prompts.append(contents)
        return Answer(FakeGemini.payload)


def gemini_clip(start, options, **extra):
    return {"start_time": start, "end_time": start + 20, "hook_time": start + 1, "virality_score": 90,
            "key_quotes": [], "title": "Legacy Title", "title_suggestion": "",
            "caption_suggestion": "", "hashtag_suggestion": "", "title_options": options, **extra}


@pytest.fixture
def api(monkeypatch):
    FakeGemini.prompts = []
    monkeypatch.setattr(main.genai, "Client", FakeGemini)
    monkeypatch.setattr(main, "get_flash_models_for_key", lambda client: [])
    monkeypatch.setattr(main, "fetch_video_metadata", lambda *a, **k: {
        "title": "Uji", "channel": "Kanal", "duration": 120.0, "heatmap": [],
        "is_live": False, "live_status": "not_live"})
    monkeypatch.setattr(main, "fetch_transcript", lambda *a, **k: [
        {"text": f"kalimat nomor {i}", "start": i * 5.0, "duration": 5.0} for i in range(24)])
    monkeypatch.delenv("MOCK_MODE", raising=False)
    return TestClient(main.app)


def analyze(api):
    res = api.post("/api/analyze", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "duration": "30s"},
                   headers={"X-Gemini-Api-Key": "AIzaSyFAKE_USER_KEY_0123456789abcdefgh"})
    events = [json.loads(line[5:]) for line in res.text.splitlines() if line.startswith("data:")]
    results = [e["result"] for e in events if "result" in e]
    assert results, [e for e in events if "error" in e]
    return results[-1]


def test_analysis_returns_checked_options_and_one_active_title(api):
    FakeGemini.payload = {"summary": "s", "clips": [
        gemini_clip(10, [{"text": GOOD[0], "angle": "question"},
                         {"text": "Ini Adalah Judul Yang Punya Delapan Kata Panjang", "angle": "x"},
                         {"text": GOOD[1], "angle": "statement"}], content_type="edukasi/kesehatan"),
        gemini_clip(60, []),  # no options: the legacy title is used
    ]}
    clips = analyze(api)["clips"]
    first, second = clips
    assert first["title_options"] == [GOOD[0], GOOD[1]]
    # The first option is the active title everywhere: list, preview and render.
    assert first["title"] == first["title_suggestion"] == GOOD[0]
    assert first["content_type"] == "edukasi/kesehatan"
    assert second["title_options"] == ["Legacy Title"] and second["title"] == "Legacy Title"


def test_the_prompt_sent_to_gemini_has_the_new_title_rules(api):
    FakeGemini.payload = {"summary": "s", "clips": [gemini_clip(10, [{"text": GOOD[0]}])]}
    analyze(api)
    prompt = FakeGemini.prompts[-1]
    assert "HOOK TITLE RULES" in prompt
    assert f"at most {title_rules.MAX_TITLE_WORDS} words" in prompt
    assert "Match output language to transcript language" not in prompt  # titles are always Indonesian now
