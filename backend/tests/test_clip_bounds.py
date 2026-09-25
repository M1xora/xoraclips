"""
Issue #35: clip starts/ends are moved to transcript line edges so a clip does
not open or close mid-line. Gemini and YouTube are fakes: nothing goes online.
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
import routes_analyze
from clip_bounds import EDGE_TOLERANCE_SECONDS, MAX_SHIFT_SECONDS, TAIL_SECONDS, Lines, snap_clip, snap_clips

FIXTURES = Path(__file__).parent / "fixtures" / "transcripts"


def line(start, end, text="x"):
    return {"start": start, "end": end, "text": text}


# Lines 0-4, 4-8, 8-12 with a gap, then 14-18.
PLAIN = [line(0, 4), line(4, 8), line(8, 12), line(14, 18)]


def snap(start, end, lines=PLAIN, lo=0.0, hi=100.0):
    return snap_clip(start, end, Lines(lines), lo, hi)


# --- one clip ------------------------------------------------------------------------

def test_a_start_mid_line_goes_back_to_the_line_start():
    assert snap(5.5, 8)[0] == 4


def test_an_end_mid_line_goes_to_the_line_end():
    # 8-12 is followed by silence until 14, so the tail fits.
    assert snap(0, 9.5)[1] == 12 + TAIL_SECONDS


def test_the_tail_never_reaches_into_the_next_line():
    # 4-8 is followed straight away by 8-12.
    assert snap(0, 6)[1] == 8


def test_times_already_on_an_edge_stay():
    assert snap(4, 8) == (4, 8)


def test_times_in_a_gap_stay():
    assert snap(12.5, 13.5) == (12.5, 13.5)


def test_an_end_exactly_on_a_line_end_with_silence_after_gets_the_tail():
    assert snap(0, 12)[1] == 12 + TAIL_SECONDS


def test_ends_move_at_most_max_shift():
    long_line = [line(0, 30)]
    assert snap(0.5 + MAX_SHIFT_SECONDS + 1, 10, long_line)[0] == 0.5 + MAX_SHIFT_SECONDS + 1
    assert snap(0, 30 - MAX_SHIFT_SECONDS - 1, long_line)[1] == 30 - MAX_SHIFT_SECONDS - 1


def test_the_users_range_is_respected():
    assert snap(5.5, 9.5, lo=5.0, hi=10.0) == (5.0, 10.0)


def test_rolling_auto_captions_end_where_the_next_line_starts():
    # YouTube auto captions: each line stays up until the line after next.
    rolling = [line(0.0, 6.2), line(4.2, 7.7), line(6.2, 15.1), line(7.7, 12.0)]
    # 5.0 is inside "4.2 until 6.2" (when line 3 starts), not until 7.7.
    assert snap(0.0, 5.0, rolling)[1] == 6.2
    assert snap(6.9, 12.0, rolling)[0] == 6.2


def test_unsorted_lines_are_handled():
    assert snap(5.5, 9.5, list(reversed(PLAIN))) == (4, 12 + TAIL_SECONDS)


def test_no_transcript_leaves_the_clip_alone():
    assert snap(5.5, 9.5, []) == (5.5, 9.5)


# --- several clips -------------------------------------------------------------------

def test_order_is_kept():
    assert snap_clips([(9, 13.5), (1, 6)], PLAIN, 0, 100) == [(8, 13.5), (0, 8)]


def test_snapping_never_creates_an_overlap():
    # Clip A ends at 5, clip B starts at 6: both inside line 4-8.
    out = snap_clips([(0.5, 5), (6, 11)], PLAIN, 0, 100)
    (a_start, a_end), (b_start, b_end) = out
    assert a_end <= b_start
    assert a_end >= 5 and b_start <= 6  # neither ends up shorter than Gemini made it


def test_clips_gemini_made_overlapping_stay_as_they_were_snapped():
    assert snap_clips([(0.5, 9), (5, 13.5)], PLAIN, 0, 100) == [(0, 12 + TAIL_SECONDS), (4, 13.5)]


@pytest.mark.parametrize("name", ["komedi_qedBB492cQY", "kesehatan_YGjXfLsuG8k", "debat_Mwmex7kDaaE"])
def test_real_transcripts_every_snapped_end_is_on_an_edge(name):
    data = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    lines = [line(l["start"], l["start"] + l["duration"]) for l in data["transcript"]]
    edges = Lines(lines)
    # Clips every 37s, 23s long: arbitrary seconds that mostly land mid-line.
    clips = [(t, t + 23.0) for t in range(5, int(data["duration"]) - 30, 37)]
    for (s0, e0), (s, e) in zip(clips, snap_clips(clips, lines, 0, data["duration"])):
        tol = EDGE_TOLERANCE_SECONDS
        assert s <= s0 + tol and e >= e0 - tol
        assert s0 - s <= MAX_SHIFT_SECONDS + tol and e - e0 <= MAX_SHIFT_SECONDS + TAIL_SECONDS
        assert edges._containing(s) is None or s in edges.starts
        assert edges._containing(e - 0.001) is None or e in edges.ends or e in edges.starts \
            or any(abs(e - (x + TAIL_SECONDS)) < 0.01 for x in edges.ends)


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


def gemini_clip(start, end, hook):
    return {"start_time": start, "end_time": end, "hook_time": hook, "virality_score": 90,
            "key_quotes": [], "title": "Legacy Title", "title_suggestion": "",
            "caption_suggestion": "", "hashtag_suggestion": "", "title_options": []}


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(routes_analyze.genai, "Client", FakeGemini)
    monkeypatch.setattr(routes_analyze, "get_flash_models_for_key", lambda client: [])
    monkeypatch.setattr(routes_analyze, "fetch_video_metadata", lambda *a, **k: {
        "title": "Uji", "channel": "Kanal", "duration": 120.0, "heatmap": [],
        "is_live": False, "live_status": "not_live"})
    # Lines of 4s every 5s: 1s of silence after each.
    monkeypatch.setattr(routes_analyze, "fetch_transcript", lambda *a, **k: [
        {"text": f"kalimat nomor {i}", "start": i * 5.0, "duration": 4.0} for i in range(24)])
    monkeypatch.delenv("MOCK_MODE", raising=False)
    return TestClient(main.app)


def analyze(api, **body):
    res = api.post("/api/analyze",
                   json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "duration": "30s", **body},
                   headers={"X-Gemini-Api-Key": "AIzaSyFAKE_USER_KEY_0123456789abcdefgh"})
    events = [json.loads(l[5:]) for l in res.text.splitlines() if l.startswith("data:")]
    results = [e["result"] for e in events if "result" in e]
    assert results, [e for e in events if "error" in e]
    return results[-1]


def test_analysis_returns_snapped_clips_with_their_transcript(api):
    FakeGemini.payload = {"summary": "s", "clips": [gemini_clip(12.5, 27.0, 13.0)]}
    clip = analyze(api)["clips"][0]
    assert (clip["start_time"], clip["end_time"]) == (10.0, 29.4)
    assert clip["hook_time"] == 13.0
    assert clip["transcript"].startswith("kalimat nomor 2") and clip["transcript"].endswith("kalimat nomor 5")


def test_a_hook_outside_the_clip_becomes_the_clip_start(api):
    FakeGemini.payload = {"summary": "s", "clips": [gemini_clip(12.5, 27.0, 50.0)]}
    assert analyze(api)["clips"][0]["hook_time"] == 10.0


def test_the_search_range_still_holds(api):
    FakeGemini.payload = {"summary": "s", "clips": [gemini_clip(12.5, 27.0, 13.0)]}
    clip = analyze(api, range_start=11.0, range_end=28.0)["clips"][0]
    assert (clip["start_time"], clip["end_time"]) == (11.0, 28.0)


def test_backup_clips_are_snapped_too(api, monkeypatch):
    # Lines of 4s every 7s: a 30s backup window mostly starts or ends inside
    # a line, and has to be moved to that line's edge.
    lines = [{"text": f"kalimat nomor {i}", "start": i * 7.0, "duration": 4.0} for i in range(17)]
    monkeypatch.setattr(routes_analyze, "fetch_transcript", lambda *a, **k: [dict(l) for l in lines])
    FakeGemini.payload = {"summary": "", "clips": []}
    clips = analyze(api)["clips"]
    assert clips
    edges = Lines([{"start": l["start"], "end": l["start"] + l["duration"]} for l in lines])
    for clip in clips:
        assert edges._containing(clip["start_time"]) is None or clip["start_time"] in edges.starts
        assert edges._containing(clip["end_time"] - 0.001) is None
        # A 30s window, widened by at most one line on each side (+ tail).
        assert 30 <= clip["end_time"] - clip["start_time"] <= 30 + 2 * 7 + TAIL_SECONDS


def test_a_time_gemini_did_not_give_as_a_number_does_not_break_the_analysis(api):
    FakeGemini.payload = {"summary": "s", "clips": [gemini_clip(None, "1:05", 1.0), gemini_clip(10.0, 27.0, 11.0)]}
    clips = analyze(api)["clips"]
    assert (clips[1]["start_time"], clips[1]["end_time"]) == (10.0, 29.4)


# --- rounding in the prompt ---------------------------------------------------------------

def test_a_time_rounded_from_a_line_edge_counts_as_that_edge():
    # The prompt shows 140.88 as 140.9; Gemini answers 140.9.
    lines = [line(137.6, 140.88), line(140.88, 144.2)]
    assert snap(130.0, 140.9, lines, hi=200)[1] == 140.88
    assert snap(140.9, 144.0, lines, hi=200)[0] == 140.88
    # 0.1s off is a real choice, not rounding.
    assert snap(130.0, 141.0, lines, hi=200)[1] == 144.2 + TAIL_SECONDS


# --- finishing the sentence (punctuated transcripts) -------------------------------------

from clip_bounds import MID_LINE_TAIL_SECONDS, SENTENCE_REACH_SECONDS  # noqa: E402

# Four 4s lines back to back; the sentence ends at the end of line 2 and in
# the middle of line 4 ("... cukup. Apalagi lawan").
PUNCT = [
    line(0, 4, "Kalau pabrik yang kecil-kecil"),
    line(4, 8, "pasti bangkrut karena volume kita."),
    line(8, 12, "Terus yang kedua jangan terlalu"),
    line(12, 16, "enggak cukup. Apalagi lawan"),
    line(16, 20, "China produksi sebulan."),
]


def test_an_end_mid_sentence_moves_to_the_sentence_end_at_a_line_end():
    assert snap(0, 4, PUNCT) == (0, 8)


def test_a_sentence_end_inside_a_line_is_estimated_from_its_position():
    s, e = snap(8, 12, PUNCT)
    # "enggak cukup." is 13 of 27 characters: 12 + 4 * 13/27 = 13.93, + tail.
    assert s == 8 and e == round(12 + 4 * 13 / 27 + MID_LINE_TAIL_SECONDS, 2)


def test_a_stop_just_before_the_end_with_words_after_it_does_not_count():
    # The clip ends after "... dong. He": "He" starts the next sentence.
    lines = [line(0, 4, "terbitkan sertifikat dong. He"), line(4, 8, "enggak. Nah, terus")]
    s, e = snap(0, 4, lines)
    assert e == round(4 + 4 * len("enggak.") / len("enggak. Nah, terus") + MID_LINE_TAIL_SECONDS, 2)


def test_an_end_already_after_a_sentence_stays():
    assert snap(0, 8, PUNCT) == (0, 8)


def test_the_sentence_end_must_be_within_reach():
    far = [line(0, 4, "satu."), line(4, 8, "dua tiga")] + [
        line(8 + 4 * k, 12 + 4 * k, "lanjut terus") for k in range(3)] + [line(20, 24, "selesai.")]
    assert snap(0, 8, far, hi=100)[1] == 8  # the stop at 24 is 16s away
    assert SENTENCE_REACH_SECONDS < 16


def test_a_transcript_without_punctuation_is_not_extended():
    bare = [line(l["start"], l["end"], l["text"].replace(".", "")) for l in PUNCT]
    assert snap(0, 4, bare) == (0, 4)


def test_finishing_the_sentence_never_creates_an_overlap():
    # Clip B starts at 5, inside the sentence clip A would be extended into.
    (a_start, a_end), (b_start, _) = snap_clips([(0, 4), (5, 12)], PUNCT, 0, 100)
    assert a_end <= b_start


# --- review findings -----------------------------------------------------------------------

def test_the_edge_tolerance_never_leaves_the_users_range():
    lines = [line(5, 10.96), line(11.5, 20), line(30.02, 35)]
    s, e = snap(11.0, 29.97, lines, lo=11.0, hi=29.97)
    assert s >= 11.0 and e <= 29.97


def test_no_overlap_with_a_clip_further_along_either():
    # B lies inside A (Gemini's own overlap); snapping A must still not run into C.
    lines = [line(0, 4), line(4, 8), line(8, 14), line(14, 20)]
    out = snap_clips([(0.5, 9.5), (5, 9), (12.5, 20)], lines, 0, 100)
    assert out[0][1] <= out[2][0]


def test_a_sentence_end_later_in_the_same_line_is_used():
    # Gemini ends at 13.0, inside "enggak cukup. Apalagi lawan" (12-16): the
    # sentence ends at ~13.93, not at the next stop at 20.
    assert snap(8, 13.0, PUNCT)[1] == round(12 + 4 * 13 / 27 + MID_LINE_TAIL_SECONDS, 2)
