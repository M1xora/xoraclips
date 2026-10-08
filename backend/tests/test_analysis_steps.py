"""The steps of an analysis (analysis.py, #74), each on its own."""
import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend import analysis, clip_lengths, title_rules  # noqa: E402
from backend.analysis import AnalysisError  # noqa: E402


def caption_lines(n, step=5.0):
    return [{"text": f"kalimat {i}.", "start": i * step, "duration": step} for i in range(n)]


def enriched(n, step=5.0, engagement=0.0):
    return [{"start": i * step, "end": (i + 1) * step, "text": f"kalimat {i}.", "engagement": engagement}
            for i in range(n)]


# --- transcript -------------------------------------------------------------------------

def test_a_known_duration_is_kept_and_an_unknown_one_comes_from_the_last_line():
    assert analysis.estimate_duration(120.0, caption_lines(3)) == 120.0
    assert analysis.estimate_duration(0.0, caption_lines(3)) == 15.0
    assert analysis.estimate_duration(0.0, []) == 0.0


def test_without_a_range_everything_is_searched():
    lines = caption_lines(4)
    assert analysis.apply_range(lines, 20.0, None, None) == (lines, 0.0, 20.0, 20.0)


def test_a_range_keeps_the_lines_that_touch_it_and_its_length_becomes_the_duration():
    lines, start, end, duration = analysis.apply_range(caption_lines(10), 50.0, 12.0, 27.0)
    assert [l["start"] for l in lines] == [10.0, 15.0, 20.0, 25.0]
    assert (start, end, duration) == (12.0, 27.0, 15.0)


def test_a_range_past_the_video_is_brought_inside_it():
    _, start, end, duration = analysis.apply_range(caption_lines(10), 50.0, -5.0, 999.0)
    assert (start, end, duration) == (0.0, 50.0, 50.0)


def test_a_backwards_range_and_a_range_without_lines_are_refused():
    with pytest.raises(AnalysisError, match="start time must be less than end time") as backwards:
        analysis.apply_range(caption_lines(10), 50.0, 30.0, 10.0)
    assert backwards.value.status == 400
    with pytest.raises(AnalysisError, match="No subtitles found in the specified range 60.0s to 70.0s"):
        analysis.apply_range(caption_lines(10), 100.0, 60.0, 70.0)


def test_each_line_gets_the_audience_interest_of_its_moment():
    heatmap = [{"start_time": 0.0, "end_time": 5.0, "value": 0.2},
               {"start_time": 5.0, "end_time": 10.0, "value": 0.9}]
    lines = analysis.enrich_transcript([{"text": "a", "start": 0.0, "duration": 5.0},
                                        {"text": "b", "start": 5.0, "duration": 5.0}], heatmap)
    assert lines == [{"start": 0.0, "end": 5.0, "text": "a", "engagement": 0.2},
                     {"start": 5.0, "end": 10.0, "text": "b", "engagement": 0.9}]
    assert analysis.enrich_transcript(caption_lines(1), [])[0]["engagement"] == 0.0


# --- prompt -----------------------------------------------------------------------------

def prompt_for(lines, heatmap=(), channel="Kanal", custom_prompt=None, is_long_video=False):
    return analysis.build_prompt(
        lines, heatmap=list(heatmap), title="Judul", channel=channel, start_bound=0.0, end_bound=100.0,
        duration=100.0, clip_duration="30s", clip_range="3-5", custom_prompt=custom_prompt,
        is_long_video=is_long_video)


def test_the_prompt_carries_the_video_the_rules_and_every_line():
    prompt, n_lines = prompt_for(enriched(3))
    assert n_lines == 3
    assert "- Video Title: Judul\n- Channel / Host / Creator: Kanal\n" in prompt
    assert "0.0|5.0 kalimat 0.\n5.0|10.0 kalimat 1.\n10.0|15.0 kalimat 2." in prompt
    assert "HOOK TITLE RULES" in prompt and clip_lengths.prompt_range("30s") in prompt
    assert "No audience interest data" in prompt and "CRITICAL FOCUS" not in prompt


def test_audience_interest_goes_in_a_column_only_when_there_is_a_heatmap():
    prompt, _ = prompt_for(enriched(1, engagement=0.456), heatmap=[{"value": 1}])
    assert "0.0|5.0|0.46 kalimat 0." in prompt and "Prioritise high-interest peaks" in prompt
    prompt, _ = prompt_for(enriched(1, engagement=0.0), heatmap=[{"value": 1}])
    assert "0.0|5.0 kalimat 0." in prompt


def test_the_users_focus_and_a_missing_channel():
    prompt, _ = prompt_for(enriched(1), channel="", custom_prompt="  bagian lucu  ")
    assert 'matching the following query/theme: "bagian lucu"' in prompt
    assert "Channel / Host / Creator" not in prompt


def test_a_long_transcript_is_cut(caplog):
    with caplog.at_level(logging.WARNING, logger="xoraclips"):
        prompt, n_lines = prompt_for(enriched(900, step=1.0))
    assert n_lines == 800 and "799.0|800.0 kalimat 799." in prompt and "kalimat 800." not in prompt
    assert "Transcript 900 lines — truncating to 800." in caplog.text
    assert prompt_for(enriched(900, step=1.0), is_long_video=True)[1] == 900


def test_retired_models_become_the_current_flash():
    assert analysis.pick_model(" gemini-3.5-flash-lite ") == "gemini-3.5-flash-lite"
    assert analysis.pick_model(None) == "gemini-2.5-flash"
    assert analysis.pick_model("gemini-1.0-pro") == "gemini-2.5-flash"
    assert analysis.pick_model("Gemini-Pro-Vision") == "gemini-2.5-flash"


@pytest.mark.parametrize("elapsed, stage, progress", [
    (0, "Neural Context Loading", 12), (4, "Neural Context Loading", 28),
    (5, "Retention Spike Cross-Analysis", 35), (11, "Retention Spike Cross-Analysis", 53),
    (12, "Viral Hook & Curiosity Detection", 55), (19, "Viral Hook & Curiosity Detection", 70),
    (20, "Coherence & Sentence Boundary Snapping", 72), (29, "Coherence & Sentence Boundary Snapping", 83),
    (30, "Virality Scoring & Selection", 85), (41, "Virality Scoring & Selection", 92),
    (42, "Social Media Metadata Synthesis", 92), (300, "Social Media Metadata Synthesis", 95),
])
def test_the_waiting_stages_follow_the_clock_and_never_go_back(elapsed, stage, progress):
    got_stage, detail, got_progress = analysis.waiting_stage(elapsed, 24, "gemini-x", "3-5")
    assert (got_stage, got_progress) == (stage, progress)
    assert detail


def test_waiting_progress_only_goes_up():
    progress = [analysis.waiting_stage(s, 24, "m", "3-5")[2] for s in range(0, 200)]
    assert progress == sorted(progress) and max(progress) == 95


# --- Gemini's answer --------------------------------------------------------------------

class Answer:
    def __init__(self, text="", parsed=None):
        self.text = text
        self.parsed = parsed


PAYLOAD = {"summary": "s", "clips": [{"title": "t", "start_time": 1.5, "end_time": 2.0, "hook_time": 1.6,
                                      "virality_score": 80, "key_quotes": ["q"]}]}


def test_the_answer_text_is_read_as_json_with_or_without_a_code_fence():
    assert analysis.parse_gemini_answer(Answer(json.dumps(PAYLOAD)), "m") == PAYLOAD
    assert analysis.parse_gemini_answer(Answer("```json\n" + json.dumps(PAYLOAD) + "\n```"), "m") == PAYLOAD


def test_an_unreadable_or_empty_answer_is_none(caplog):
    with caplog.at_level(logging.WARNING, logger="xoraclips"):
        assert analysis.parse_gemini_answer(Answer("not json"), "gemini-x") is None
    assert "JSON parsing error from gemini-x" in caplog.text
    assert analysis.parse_gemini_answer(Answer(""), "m") is None


def test_the_sdks_parsed_object_becomes_the_same_plain_data():
    parsed = analysis.VideoAnalysis.model_validate({"summary": "s", "clips": [{
        "title": "t", "start_time": 1, "end_time": 2, "hook_time": 1.5, "virality_score": 9, "key_quotes": ["q"],
        "title_options": [{"text": "a", "angle": "b"}]}]})
    data = analysis.parse_gemini_answer(Answer(text="ignored", parsed=parsed), "m")
    assert data["summary"] == "s"
    assert data["clips"][0] == {
        "title": "t", "start_time": 1.0, "end_time": 2.0, "hook_time": 1.5, "virality_score": 9,
        "key_quotes": ["q"], "title_suggestion": "", "caption_suggestion": "", "hashtag_suggestion": "",
        "title_options": [{"text": "a", "angle": "b"}], "content_type": ""}


# --- backup clips and finishing ---------------------------------------------------------

def test_backup_clips_sit_around_the_peaks_inside_the_range_without_overlapping():
    lines = enriched(40)
    lines[20]["engagement"] = 0.9
    lines[5]["engagement"] = 0.8
    clips = analysis.backup_clips(lines, "30s", 10.0, 190.0)
    assert clips and all(c["is_fallback"] for c in clips)
    spans = sorted((c["start_time"], c["end_time"]) for c in clips)
    assert all(10.0 <= s < e <= 190.0 for s, e in spans)
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))
    # Issue #98: no title of their own; finish_clips gives them a checked one.
    assert "title" not in clips[0] and clips[0]["hook_time"] == 100.0
    assert clips[0]["key_quotes"] and clips[0]["caption_suggestion"].endswith("#viral #trending")
    # The user-visible text is Indonesian, like the title the rules give them.
    assert clips[0]["caption_suggestion"].startswith("Momen pilihan dari video:")


def gemini_clip(start, end, **extra):
    return {"title": "Legacy", "start_time": start, "end_time": end, "hook_time": start + 1,
            "virality_score": 80, "key_quotes": ["q"], "caption_suggestion": "Seru #FYP",
            "hashtag_suggestion": "#Podcast", "title_options": [{"text": "Ternyata Begini Rasanya"}], **extra}


def test_finished_clips_sit_on_line_edges_with_their_own_text_and_lowercase_hashtags():
    clip, = analysis.finish_clips([gemini_clip(11, 24)], enriched(12), "30s", 0.0, 60.0, "Kanal")
    assert (clip.start_time, clip.end_time) == (10.0, 25.0)
    assert clip.transcript == "kalimat 2. kalimat 3. kalimat 4."
    assert clip.hook_time == 12
    assert (clip.caption_suggestion, clip.hashtag_suggestion) == ("Seru #fyp", "#podcast")
    assert clip.title == clip.title_suggestion == clip.title_options[0] == "Ternyata Begini Rasanya"


def test_a_hook_outside_the_clip_moves_to_its_start():
    clip, = analysis.finish_clips([gemini_clip(10, 25, hook_time=99)], enriched(12), "30s", 0.0, 60.0, "")
    assert clip.hook_time == clip.start_time == 10.0


def test_a_first_person_title_is_credited_to_the_channel():
    clip, = analysis.finish_clips([gemini_clip(10, 25, title_options=[{"text": "Saya Mencoba Lari Tiap Hari"}])],
                                  enriched(12), "30s", 0.0, 60.0, "dr. Tirta")
    assert clip.title == "dr. Tirta Mencoba Lari Tiap Hari"


def real_backup_clips(n_lines=80, duration="30s", lo=0.0, hi=400.0):
    """Backup clips from the real producer, so the tests cannot drift from it."""
    lines = enriched(n_lines)
    for i in (5, 20, 40):
        if i < len(lines):
            lines[i]["engagement"] = 0.9 - i / 100
    return analysis.backup_clips(lines, duration, lo, hi), lines


def test_backup_clip_titles_go_through_the_title_rules():
    # Issue #98: with no options and no old title, the rules land on the
    # Indonesian generic title instead of the old hardcoded English one.
    raw, lines = real_backup_clips()
    # The producer writes no title of its own: that is what sends these
    # clips to the rules instead of straight to the Studio.
    assert all("title" not in c and "title_suggestion" not in c for c in raw)
    clips = analysis.finish_clips(raw, lines, "30s", 0.0, 400.0, "Kanal")
    assert clips
    for clip in clips:
        assert title_rules.title_problem(clip.title) is None
        assert clip.title == clip.title_suggestion
        assert clip.title_options == [clip.title]
        assert clip.title.startswith(title_rules.generic_fallback().split()[0])


def test_every_backup_clip_gets_its_own_title():
    """Issue #98: identical names give the editor no way to tell clips apart."""
    raw, lines = real_backup_clips()
    clips = analysis.finish_clips(raw, lines, "30s", 0.0, 400.0, "Kanal")
    assert len(clips) > 1, "need more than one backup clip to test this"
    titles = [c.title for c in clips]
    assert len(set(titles)) == len(titles), titles
    assert titles[0] == title_rules.generic_fallback(1) == f"{title_rules.generic_fallback()} 1"


def test_backup_clips_are_not_blamed_on_gemini_in_the_log(caplog):
    """Issue #98: they carry no title by design, so that is not a fault."""
    raw, lines = real_backup_clips()
    with caplog.at_level(logging.WARNING, logger="xoraclips.titles"):
        analysis.finish_clips(raw, lines, "30s", 0.0, 400.0, "Kanal")
    assert "Gemini" not in caplog.text
    assert not [r for r in caplog.records if r.name == "xoraclips.titles"]


def test_the_response_has_the_whole_transcript_and_a_lowercase_summary():
    heatmap = [{"start_time": 0, "end_time": 5, "value": 1}]
    result = analysis.build_response(video_id="abc", title="T", channel="C", duration=60.0, heatmap=heatmap,
                                     summary="Ringkas #Podcast", clips=[], enriched_transcript=enriched(2),
                                     model="gemini-x")
    assert result.summary == "Ringkas #podcast" and result.model == "gemini-x"
    assert [p.model_dump() for p in result.heatmap] == [{"start_time": 0.0, "end_time": 5.0, "value": 1.0}]
    assert [l.text for l in result.transcript] == ["kalimat 0.", "kalimat 1."]


# --- answers with the wrong shape (found in the #72 review) -----------------------------

def test_an_answer_that_is_not_an_object_is_unreadable():
    for text in ("[1, 2, 3]", '"just text"', "42", "null"):
        assert analysis.parse_gemini_answer(Answer(text), "m") is None, text


def test_clip_fields_of_the_wrong_type_are_cleaned_instead_of_breaking_the_analysis():
    data = analysis.parse_gemini_answer(Answer(json.dumps({"summary": None, "clips": [
        {"title": 7, "start_time": "10", "end_time": "25.5", "hook_time": "12", "virality_score": None,
         "key_quotes": "one quote", "caption_suggestion": 5, "hashtag_suggestion": None},
        {"start_time": 30, "end_time": 45, "hook_time": "soon", "virality_score": 87.6, "key_quotes": ["a", 2, None]},
        "not a clip",
    ]})), "m")
    assert data["summary"] == ""
    first, second = data["clips"]  # "not a clip" is dropped
    assert (first["start_time"], first["end_time"], first["hook_time"]) == (10.0, 25.5, 12.0)
    assert first["virality_score"] == 0 and first["key_quotes"] == ["one quote"]
    assert (first["title"], first["caption_suggestion"], first["hashtag_suggestion"]) == ("7", "5", "")
    assert second["hook_time"] is None and second["virality_score"] == 87 and second["key_quotes"] == ["a", "2"]


def test_clips_that_are_not_a_list_or_not_clips_make_the_answer_unreadable():
    for clips in ('"none"', "null", '["a", 1]'):
        assert analysis.parse_gemini_answer(Answer('{"summary": "s", "clips": %s}' % clips), "m") is None, clips
    # No clips at all is a real answer: the next model is asked, then backup clips.
    assert analysis.parse_gemini_answer(Answer('{"summary": "s"}'), "m") == {"summary": "s", "clips": []}
    assert analysis.parse_gemini_answer(Answer('{"summary": "s", "clips": []}'), "m") == {"summary": "s", "clips": []}


def test_gemini_cannot_mark_its_own_clip_as_a_backup_clip():
    data = analysis.parse_gemini_answer(Answer(json.dumps({"summary": "s", "clips": [
        {"start_time": 10, "end_time": 25, "is_fallback": True}]})), "m")
    assert "is_fallback" not in data["clips"][0]


def test_cleaned_clips_finish_without_errors():
    data = analysis.parse_gemini_answer(Answer(json.dumps({"summary": "s", "clips": [
        {"start_time": "10", "end_time": "25", "hook_time": "12", "virality_score": None, "title_options": "x"},
        {"start_time": float("inf"), "end_time": "nan", "hook_time": 1e400}]})), "m")
    clips = analysis.finish_clips(data["clips"], enriched(12), "30s", 0.0, 60.0, "Kanal")
    assert [(c.start_time, c.hook_time, c.virality_score) for c in clips][0] == (10.0, 12.0, 0)


def test_the_backend_asks_for_the_running_loop_not_the_old_get_event_loop():
    # asyncio.get_event_loop() inside a coroutine is the old spelling; inside
    # one the loop is always running (#74).
    backend = Path(__file__).resolve().parents[1]
    offenders = [p.name for p in backend.glob("*.py") if "get_event_loop()" in p.read_text(encoding="utf-8")]
    assert offenders == []
