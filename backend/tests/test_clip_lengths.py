"""
Issue #34: 2- and 3-minute clips. Target lengths, the 179s limit, the clip
count that fits, and backup clips. Gemini and YouTube are fakes.
"""
import json

import pytest
from fastapi.testclient import TestClient

import main
from clip_bounds import TAIL_SECONDS, Lines
from clip_lengths import (
    DURATIONS, MAX_CLIP_SECONDS, backup_windows, cap_length, clip_count_range,
    label, prompt_range, prompt_rules, target_seconds,
)
from video_engine import render_timeouts


# --- targets -----------------------------------------------------------------------------

def test_the_old_ranges_are_unchanged():
    assert prompt_range("15s") == "10-20s"
    assert prompt_range("30s") == "20-40s"
    assert prompt_range("60s") == "45-75s"


def test_two_and_three_minutes():
    assert prompt_range("120s") == "90-130s" and target_seconds("120s") == 120
    assert prompt_range("180s") == "140-175s" and target_seconds("180s") == 175
    assert (label("120s"), label("180s"), label("60s")) == ("2m", "3m", "60s")


def test_no_range_asks_for_more_than_the_limit():
    assert all(longest <= MAX_CLIP_SECONDS for _, longest, _ in DURATIONS.values())


def test_only_long_clips_get_the_complete_idea_rule():
    assert prompt_rules("15s") == prompt_rules("30s") == prompt_rules("60s") == ""
    assert "ONE complete idea" in prompt_rules("120s")
    assert "ONE complete idea" in prompt_rules("180s")
    assert "HARD RULE: every clip is 140-175 seconds long" in prompt_rules("180s")


# --- clip count --------------------------------------------------------------------------

def test_counts_that_fit_are_as_before():
    assert clip_count_range(5, False, 3600, "30s") == ("4-7", None)
    assert clip_count_range(10, False, 3600, "30s") == ("8-13", None)
    assert clip_count_range(20, False, 3600, "30s") == ("15-25", None)
    assert clip_count_range(None, False, 3600, "30s") == ("10-30", None)
    assert clip_count_range(None, True, 7200, "30s") == ("15-60", None)


def test_ten_three_minute_clips_do_not_fit_in_fifteen_minutes():
    # 60% of 900s = 540s, / 175s = 3 clips.
    assert clip_count_range(10, False, 900, "180s") == ("3-3", 3)


def test_the_upper_end_is_brought_down_even_when_the_count_itself_fits():
    # 5 requested -> 4-7; 60% of 1750s / 175s = 6 fit: 4-6, nothing to tell the user.
    assert clip_count_range(5, False, 1750, "180s") == ("4-6", None)


def test_the_default_range_is_capped_too():
    # 60% of 600s / 120s = 3.
    assert clip_count_range(None, False, 600, "120s") == ("3-3", None)


def test_a_span_shorter_than_one_clip_still_asks_for_one():
    assert clip_count_range(3, False, 100, "180s") == ("1-1", 1)


# --- length limit ------------------------------------------------------------------------

def line(start, end, text="x"):
    return {"start": start, "end": end, "text": text}


def test_a_short_clip_is_not_touched():
    assert cap_length(10, 100, Lines([line(0, 50)]), 1000) == 100


def test_a_long_clip_is_cut_back_to_the_last_line_end_with_its_tail():
    # 170-178 is followed by silence until 181: the tail fits inside 179.
    lines = Lines([line(0, 100), line(100, 170), line(170, 178), line(181, 190)])
    assert cap_length(0, 185, lines, 1000) == 178 + TAIL_SECONDS


def test_the_tail_is_dropped_when_only_the_line_fits():
    lines = Lines([line(0, 100), line(100, 178.8), line(181, 190)])
    assert cap_length(0, 185, lines, 1000) == 178.8


def test_a_punctuated_transcript_is_cut_at_the_last_sentence_end():
    lines = Lines([line(0, 100, "satu dua."), line(100, 170, "tiga empat."), line(170, 190, "lima enam")])
    assert cap_length(0, 190, lines, 1000) == 170  # next line starts at once: no tail


def test_without_a_near_end_the_clip_is_cut_at_the_limit():
    assert cap_length(0, 300, Lines([line(0, 40), line(40, 300)]), 1000) == MAX_CLIP_SECONDS


def test_render_timeouts_grow_with_the_clip():
    assert render_timeouts(30) == {"encoder": 180, "cpu": 240}  # as before for short clips
    assert render_timeouts(179)["encoder"] > 179 * 3 and render_timeouts(179)["cpu"] > 179 * 4


# --- backup clips --------------------------------------------------------------------------

def test_backup_clips_do_not_overlap_at_three_minutes():
    # Peaks 25s apart: the old code made five 3-minute clips on top of each other.
    wins = backup_windows([100, 125, 150, 400, 700, 1000], "180s", 0, 1200)
    spans = sorted((s, e) for s, e, _ in wins)
    assert all(a_end <= b_start for (_, a_end), (b_start, _) in zip(spans, spans[1:]))
    assert len(wins) == 4


def test_a_backup_clip_starts_before_its_peak():
    (start, end, peak), = backup_windows([400], "120s", 0, 1200)
    assert (start, end, peak) == (370, 490, 400)


def test_three_minute_backup_clips_fit_under_the_limit():
    (start, end, _), = backup_windows([400], "180s", 0, 1200)
    assert end - start == 175 <= MAX_CLIP_SECONDS


def test_backup_clips_stay_inside_the_searched_range():
    # Range 600-700 with 60s clips: the old code made (620, 100).
    wins = backup_windows([620, 690], "60s", 600, 700)
    assert wins and all(600 <= s < e <= 700 for s, e, _ in wins)


def test_a_peak_near_the_end_keeps_the_full_length():
    (start, end, _), = backup_windows([1190], "60s", 0, 1200)
    assert (start, end) == (1140, 1200)


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

    def generate_content(self, *args, contents=None, **kwargs):
        FakeGemini.prompts.append(contents)
        return Answer(FakeGemini.payload)


def gemini_clip(start, end):
    return {"start_time": start, "end_time": end, "hook_time": start + 1, "virality_score": 90,
            "key_quotes": [], "title": "Legacy Title", "title_suggestion": "",
            "caption_suggestion": "", "hashtag_suggestion": "", "title_options": []}


@pytest.fixture
def api(monkeypatch):
    FakeGemini.prompts = []
    monkeypatch.setattr(main.genai, "Client", FakeGemini)
    monkeypatch.setattr(main, "get_flash_models_for_key", lambda client: [])
    monkeypatch.setattr(main, "fetch_video_metadata", lambda *a, **k: {
        "title": "Uji", "channel": "Kanal", "duration": 900.0, "heatmap": [],
        "is_live": False, "live_status": "not_live"})
    # Back-to-back 5s lines over 15 minutes.
    monkeypatch.setattr(main, "fetch_transcript", lambda *a, **k: [
        {"text": f"kalimat nomor {i}", "start": i * 5.0, "duration": 5.0} for i in range(180)])
    monkeypatch.delenv("MOCK_MODE", raising=False)
    return TestClient(main.app)


def post(api, **body):
    return api.post("/api/analyze",
                    json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", **body},
                    headers={"X-Gemini-Api-Key": "AIzaSyFAKE_USER_KEY_0123456789abcdefgh"})


def events(res):
    return [json.loads(l[5:]) for l in res.text.splitlines() if l.startswith("data:")]


def result(res):
    found = [e["result"] for e in events(res) if "result" in e]
    assert found, [e for e in events(res) if "error" in e]
    return found[-1]


def test_an_unknown_duration_is_refused_instead_of_becoming_30s(api):
    assert post(api, duration="90s").status_code == 422


def test_three_minutes_reaches_the_prompt(api):
    FakeGemini.payload = {"summary": "s", "clips": [gemini_clip(100.0, 270.0)]}
    result(post(api, duration="180s", target_clip_count=3))
    prompt = FakeGemini.prompts[-1]
    assert "Target clip length: 140-175s" in prompt
    assert "ONE complete idea" in prompt


def test_too_many_clips_are_capped_and_the_user_is_told(api):
    FakeGemini.payload = {"summary": "s", "clips": [gemini_clip(100.0, 270.0)]}
    res = post(api, duration="180s", target_clip_count=10)
    assert "Return 3-3 clips" in FakeGemini.prompts[-1]
    notes = [e["detail"] for e in events(res) if e.get("stage") == "Clip Count"]
    assert notes == ["10 clips of 3m do not fit in 15:00 of video: asking for at most 3."]


def test_no_clip_comes_back_longer_than_the_limit(api):
    FakeGemini.payload = {"summary": "s", "clips": [gemini_clip(100.0, 300.0)]}
    clip = result(post(api, duration="180s", target_clip_count=3))["clips"][0]
    assert clip["end_time"] - clip["start_time"] <= MAX_CLIP_SECONDS
    assert clip["end_time"] == 275.0  # the last line edge inside 100 + 179


def test_backup_clips_are_three_minutes_and_apart(api):
    FakeGemini.payload = {"summary": "", "clips": []}
    clips = result(post(api, duration="180s", target_clip_count=3))["clips"]
    spans = sorted((c["start_time"], c["end_time"]) for c in clips)
    # 175s windows, moved to line edges (5s lines): 175-180s, never over 179.
    assert spans and all(170 <= e - s <= MAX_CLIP_SECONDS for s, e in spans)
    assert all(a_end <= b_start for (_, a_end), (b_start, _) in zip(spans, spans[1:]))
