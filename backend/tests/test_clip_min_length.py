"""
Issue #38: 2m/3m clips Gemini made too short (40s for 2m) are widened to the
shortest length. Gemini and YouTube are fakes.
"""
import json

import pytest
from fastapi.testclient import TestClient

import main
from clip_bounds import Lines
from clip_lengths import DURATIONS, stretch_short_clips


def lines_every(step, count, text="kata"):
    """Back-to-back lines of `step` seconds."""
    return Lines([{"start": i * step, "end": (i + 1) * step, "text": text} for i in range(count)])


LINES = lines_every(5.0, 400)  # 2000s of 5s lines, no punctuation


def stretch(bounds, duration="120s", lo=0.0, hi=2000.0, lines=LINES):
    return stretch_short_clips(bounds, lines, duration, lo, hi)


def test_a_40s_clip_in_2m_reaches_the_minimum_not_the_target():
    (s, e), = stretch([(500.0, 540.0)])
    assert 90 <= e - s < 100  # 90s minimum, on line edges; the 120s target is not forced


def test_most_of_the_extra_time_goes_after_the_clip():
    (s, e), = stretch([(500.0, 540.0)])
    assert 500 - s < e - 540
    assert s % 5 == 0 and e % 5 == 0  # on line edges


def test_three_minutes_reaches_140s():
    (s, e), = stretch([(500.0, 560.0)], duration="180s")
    assert 140 <= e - s < 150


def test_clips_already_long_enough_are_left_alone():
    assert stretch([(500.0, 600.0)]) == [(500.0, 600.0)]


@pytest.mark.parametrize("duration", ["15s", "30s", "60s"])
def test_short_durations_are_left_alone(duration):
    assert stretch([(500.0, 510.0)], duration=duration) == [(500.0, 510.0)]


def test_a_blocked_side_gives_its_share_to_the_other():
    # The next clip starts right after this one: all the extra time goes before.
    out = stretch([(500.0, 540.0), (540.0, 640.0)])
    (s, e), nxt = out
    assert e == 540.0 and 90 <= e - s < 100
    assert nxt == (540.0, 640.0)


def test_never_runs_into_another_clip():
    out = stretch([(500.0, 540.0), (560.0, 660.0), (400.0, 480.0)])
    spans = sorted(out)
    assert all(a_end <= b_start for (_, a_end), (b_start, _) in zip(spans, spans[1:]))


def test_stays_inside_the_searched_range():
    (s, e), = stretch([(1000.0, 1040.0)], lo=990.0, hi=1060.0)
    assert 990.0 <= s and e <= 1060.0


def test_a_punctuated_transcript_ends_on_a_sentence():
    lines = Lines([{"start": i * 5.0, "end": (i + 1) * 5.0,
                    "text": "akhir kalimat." if i % 3 == 2 else "masih lanjut"} for i in range(400)])
    (s, e), = stretch([(500.0, 540.0)], lines=lines)
    assert e - s >= 90 and e % 15 == 0  # lines 2, 5, 8 ... end a sentence: every 15s


def test_the_minimums_are_the_prompt_ranges():
    assert DURATIONS["120s"][0] == 90 and DURATIONS["180s"][0] == 140


# --- through /api/analyze ---------------------------------------------------------------

class Answer:
    parsed = None

    def __init__(self, payload):
        self.text = json.dumps(payload)


class FakeGemini:
    payload = None

    def __init__(self, *args, **kwargs):
        self.models = self

    def list(self, *args, **kwargs):
        return []

    def generate_content(self, *args, **kwargs):
        return Answer(FakeGemini.payload)


def gemini_clip(start, end):
    return {"start_time": start, "end_time": end, "hook_time": start + 2, "virality_score": 90,
            "key_quotes": [], "title": "Legacy Title", "title_suggestion": "",
            "caption_suggestion": "", "hashtag_suggestion": "", "title_options": []}


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(main.genai, "Client", FakeGemini)
    monkeypatch.setattr(main, "get_flash_models_for_key", lambda client: [])
    monkeypatch.setattr(main, "fetch_video_metadata", lambda *a, **k: {
        "title": "Uji", "channel": "Kanal", "duration": 2000.0, "heatmap": [],
        "is_live": False, "live_status": "not_live"})
    monkeypatch.setattr(main, "fetch_transcript", lambda *a, **k: [
        {"text": f"kalimat nomor {i}", "start": i * 5.0, "duration": 5.0} for i in range(400)])
    monkeypatch.delenv("MOCK_MODE", raising=False)
    return TestClient(main.app)


def test_the_users_case_2m_clips_of_40s_come_back_at_least_90s(api):
    # The run in #38: gemini-3.5-flash-lite answered 43.8, 48.5, 91.2, 39.3s.
    FakeGemini.payload = {"summary": "s", "clips": [
        gemini_clip(70.0, 115.0), gemini_clip(215.0, 265.0), gemini_clip(1160.0, 1255.0), gemini_clip(1645.0, 1685.0)]}
    res = api.post("/api/analyze",
                   json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "duration": "120s", "target_clip_count": 5},
                   headers={"X-Gemini-Api-Key": "AIzaSyFAKE_USER_KEY_0123456789abcdefgh"})
    events = [json.loads(l[5:]) for l in res.text.splitlines() if l.startswith("data:")]
    clips = [e["result"] for e in events if "result" in e][-1]["clips"]
    lengths = [c["end_time"] - c["start_time"] for c in clips]
    assert all(90 <= n <= 179 for n in lengths), lengths
    assert all(c["start_time"] <= c["hook_time"] <= c["end_time"] for c in clips)
    assert clips[2]["end_time"] - clips[2]["start_time"] == 95.0  # already long enough: untouched


# --- review findings -----------------------------------------------------------------------

def test_clips_gemini_made_overlapping_do_not_become_near_duplicates():
    (a_s, a_e), (b_s, b_e) = stretch([(500.0, 540.0), (520.0, 545.0)])
    overlap = min(a_e, b_e) - max(a_s, b_s)
    assert overlap <= 20.0  # the 20s Gemini made, not more
    assert a_s <= 500 and a_e >= 540 and b_s <= 520 and b_e >= 545  # neither shrinks


def test_clips_with_broken_times_are_not_stretched():
    assert stretch([(0.0, 0.0), (500.0, 400.0)]) == [(0.0, 0.0), (500.0, 400.0)]


def test_a_sentence_end_just_before_the_wanted_end_does_not_leave_it_short():
    # Every line ends a sentence and the next line starts right at the stop.
    lines = Lines([{"start": i * 5.0, "end": (i + 1) * 5.0, "text": "selesai."} for i in range(400)])
    (s, e), = stretch([(500.0, 540.0)], lines=lines)
    assert e - s >= 90


def test_walled_in_clips_are_counted_as_still_short():
    from clip_lengths import still_short
    out = stretch([(400.0, 500.0), (500.0, 540.0), (560.0, 700.0)])
    assert out[1][1] - out[1][0] < 90 and still_short(out, "120s") == 1
