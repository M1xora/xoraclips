"""
Characterization tests for /api/analyze (#74): every event the stream sends,
the Gemini calls it makes (model + prompt hash), the waits it asks for and
the log lines it writes, for each path through the analysis, compared with
a snapshot recorded from the code before analyze_video was split up.

The three stored transcripts replay Gemini answers recorded once from the
real API (fixtures/gemini_answers), so no test here contacts Gemini.

A deliberate behaviour change updates the snapshot in its own commit:
    venv\\Scripts\\python backend\\tests\\test_analyze_stream.py
"""
import asyncio
import hashlib
import json
import logging
import sys
import threading
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend import routes_analyze, youtube_errors  # noqa: E402
from backend.youtube_errors import CaptionUnavailable, YouTubeBlocked  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
SNAPSHOT = FIXTURES / "analyze_stream_snapshot.json"
KEY = "AIzaSyFAKE_USER_KEY_0123456789abcdefgh"
URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


# --- fakes ------------------------------------------------------------------------------

class Answer:
    def __init__(self, text="", parsed=None):
        self.text = text
        self.parsed = parsed


class Model:
    def __init__(self, name, actions=("generateContent",)):
        self.name = name
        self.supported_actions = list(actions)


class FakeGemini:
    """One scenario's Gemini: `list_result` answers models.list() (the key check
    and model discovery), `answers` answers generate_content() in call order;
    the last answer repeats. An answer is a JSON-able payload, a raw string,
    an exception, ("parsed", payload) for the SDK's parsed-object path, or
    ("slow", payload): answered once FastAsyncio's clock has run 50 seconds."""
    list_result = []
    answers = []
    calls = []
    release = threading.Event()

    def __init__(self, *args, **kwargs):
        self.models = self

    def list(self, *args, **kwargs):
        if isinstance(FakeGemini.list_result, Exception):
            raise FakeGemini.list_result
        return iter(FakeGemini.list_result)

    def generate_content(self, *args, model=None, contents=None, **kwargs):
        FakeGemini.calls.append({"model": model, "prompt_sha256": sha(contents), "prompt_chars": len(contents)})
        answer = FakeGemini.answers[min(len(FakeGemini.calls), len(FakeGemini.answers)) - 1]
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, tuple) and answer[0] == "slow":
            assert FakeGemini.release.wait(10), "the slow answer was never released"
            answer = answer[1]
        if isinstance(answer, tuple):
            return Answer(parsed=routes_analyze.VideoAnalysis.model_validate(answer[1]))
        return Answer(text=answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False))


class Clock:
    """The event loop, with time() on a fake clock."""
    def __init__(self, loop, now):
        self._loop = loop
        self._now = now

    def __getattr__(self, name):
        return getattr(self._loop, name)

    def time(self):
        return self._now[0]


class FastAsyncio:
    """routes_analyze's asyncio with sleep() recorded instead of waited, and a
    fake clock: while a slow Gemini answer is pending, each timed wait() moves
    the clock on by its timeout instead of waiting, up to SLOW_SECONDS."""
    SLOW_SECONDS = 50

    def __init__(self, sleeps):
        self._sleeps = sleeps
        self._now = [1000.0]
        self._start = None

    def __getattr__(self, name):
        return getattr(asyncio, name)

    async def sleep(self, seconds, *args, **kwargs):
        self._sleeps.append(seconds)
        await asyncio.sleep(0)

    def get_event_loop(self):
        return Clock(asyncio.get_event_loop(), self._now)

    def get_running_loop(self):
        return Clock(asyncio.get_running_loop(), self._now)

    async def wait(self, tasks, *args, timeout=None, **kwargs):
        slow = any(isinstance(a, tuple) and a[0] == "slow" for a in FakeGemini.answers)
        if slow and timeout is not None and not FakeGemini.release.is_set():
            self._start = self._now[0] if self._start is None else self._start
            if self._now[0] - self._start < self.SLOW_SECONDS:
                self._now[0] += timeout
                await asyncio.sleep(0)
                return set(), set(tasks)
            FakeGemini.release.set()
        return await asyncio.wait(tasks, *args, timeout=timeout, **kwargs)


class Recorder(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = []

    def emit(self, record):
        self.lines.append(f"{record.levelname} {record.name}: {record.getMessage()}")


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- scenario data ----------------------------------------------------------------------

def lines(n, step=5.0, text="kalimat nomor {i}."):
    return [{"text": text.format(i=i), "start": i * step, "duration": step} for i in range(n)]


def meta(duration=120.0, heatmap=(), title="Uji", channel="Kanal", **extra):
    return {"title": title, "channel": channel, "duration": duration, "heatmap": list(heatmap),
            "is_live": False, "live_status": "not_live", **extra}


def clip(start, end, hook=None, score=90, **extra):
    return {"title": "Legacy Title", "start_time": start, "end_time": end,
            "hook_time": start + 1 if hook is None else hook, "virality_score": score,
            "key_quotes": ["kutipan"], "title_suggestion": "", "caption_suggestion": "Seru #Viral #FYP",
            "hashtag_suggestion": "#Podcast #Kesehatan",
            "title_options": [{"text": "Ternyata Begini Cara Kerjanya", "angle": "statement"},
                              {"text": "Kok Bisa Sesederhana Itu?", "angle": "question"}],
            "content_type": "edukasi", **extra}


GOOD = {"summary": "Ringkasan video. #Podcast #Edukasi", "clips": [clip(10, 40), clip(60, 90, score=80)]}
EMPTY = {"summary": "", "clips": []}
HEATMAP = [{"start_time": i * 10.0, "end_time": (i + 1) * 10.0, "value": round(0.1 + 0.07 * i, 2)}
           for i in range(12)]
SRT = "1\n00:00:01,000 --> 00:00:04,000\nhalo semua\n\n2\n00:00:04,000 --> 00:00:09,500\nini subtitle manual\n"


def err(text):
    return RuntimeError(text)


NOT_FOUND = "404 NOT_FOUND. models/x is not found for API version v1beta"
BUSY = "503 UNAVAILABLE. The model is overloaded. Please try again later."
QUOTA = "429 RESOURCE_EXHAUSTED. You exceeded your current quota"
BAD_KEY = "400 INVALID_ARGUMENT. API key not valid. Please pass a valid API key."
LOCKED = "403 PERMISSION_DENIED. You do not have access to this model"


def transcript_with_progress(video_id, proxy, progress):
    progress("Supadata", "Asking Supadata for captions...", 40)
    progress("Direct", "Trying YouTube directly...", 70)
    return lines(24)


def raise_(error):
    def fail(*args, **kwargs):
        raise error
    return fail


def stored(name, duration, parsed=False):
    fx = json.loads((FIXTURES / "transcripts" / f"{name}.json").read_text(encoding="utf-8"))
    answer = json.loads((FIXTURES / "gemini_answers" / f"{name}_{duration}.json").read_text(encoding="utf-8"))
    payload = ("parsed", json.loads(answer["text"])) if parsed else answer["text"]
    return {"body": {"url": f"https://www.youtube.com/watch?v={fx['video_id']}", "duration": duration,
                     "model": answer["model"]},
            "metadata": meta(fx["duration"], fx["heatmap"], fx["title"], fx["channel"]),
            "transcript": fx["transcript"], "answers": [payload]}


SCENARIOS = {
    # --- before YouTube ---
    "key_missing": {"key": None},
    "key_invalid_upfront": {"list_result": err(BAD_KEY)},
    "key_quota_upfront": {"list_result": err(QUOTA)},
    "key_check_busy_goes_on": {"list_result": err(BUSY)},
    "bad_url": {"body": {"url": "https://example.com/video"}},
    "youtube_blocked_remembered": {"blocked": True},
    "youtube_blocked_but_manual_subtitles": {"blocked": True, "body": {"subtitles": SRT}},
    # --- metadata and captions ---
    "metadata_fails": {"metadata": RuntimeError("yt-dlp exploded")},
    "metadata_http_error": {"metadata": HTTPException(status_code=400, detail="Video is private")},
    "manual_subtitles": {"body": {"subtitles": SRT, "subtitles_filename": "a.srt"}},
    "manual_subtitles_unreadable": {"body": {"subtitles": "   "}},
    "transcript_progress": {"transcript": transcript_with_progress},
    "transcript_blocked": {"transcript": YouTubeBlocked("bot check", retry_after=600)},
    "transcript_live_video": {"metadata": meta(is_live=True, live_status="is_live"),
                              "transcript": RuntimeError("no captions yet")},
    "transcript_captions_disabled": {"transcript": CaptionUnavailable(youtube_errors.CAPTIONS_DISABLED)},
    "transcript_unexpected_error": {"transcript": RuntimeError("something odd")},
    "duration_from_transcript": {"metadata": meta(duration=0.0)},
    # --- range ---
    "range_inside": {"body": {"range_start": 20, "range_end": 80}},
    "range_clamped": {"body": {"range_start": -5, "range_end": 999}},
    "range_backwards": {"body": {"range_start": 80, "range_end": 20}},
    "range_without_lines": {"transcript": lines(10), "body": {"range_start": 100, "range_end": 110}},
    # --- prompt ---
    "heatmap_focus_count": {"metadata": meta(heatmap=HEATMAP),
                            "body": {"custom_prompt": "  bagian lucu  ", "target_clip_count": 3}},
    "no_channel": {"metadata": meta(channel="")},
    "clip_count_capped": {"body": {"duration": "180s", "target_clip_count": 10}},
    "three_minute_clips": {"transcript": lines(120), "metadata": meta(duration=600.0),
                           "body": {"duration": "180s"}, "answers": [{"summary": "s", "clips": [clip(30, 100)]}]},
    "long_transcript_truncated": {"transcript": lines(900, step=1.0), "metadata": meta(duration=900.0)},
    "long_video": {"transcript": lines(900, step=4.5), "metadata": meta(duration=4000.0)},
    "outdated_model_upgraded": {"body": {"model": "gemini-1.0-pro"}},
    # --- Gemini chain ---
    "success_first_try": {},
    "discovered_models_all_missing": {"discover": False, "answers": [err(NOT_FOUND)],
                                      "list_result": [Model("models/gemini-3.5-flash"),
                                                      Model("models/gemini-3.5-flash-lite"),
                                                      Model("models/gemini-3.5-flash-tts"),
                                                      Model("models/gemini-2.5-pro"),
                                                      Model("models/gemini-3.0-flash", ("embedContent",))]},
    "missing_then_next_model": {"answers": [err(NOT_FOUND), GOOD]},
    "busy_then_retry_works": {"answers": [err(BUSY), GOOD]},
    "busy_twice_then_next_model": {"answers": [err(BUSY), err(BUSY), GOOD]},
    "quota_everywhere": {"answers": [err(QUOTA)]},
    "bad_key_during_analysis": {"answers": [err(BAD_KEY)]},
    "locked_model_everywhere": {"answers": [err(LOCKED)]},
    "missing_everywhere": {"answers": [err(NOT_FOUND)]},
    "busy_then_missing_reports_busy": {"answers": [err(BUSY), err(BUSY), err(NOT_FOUND)]},
    "unknown_error_everywhere": {"answers": [err("something unexpected")]},
    "unparseable_then_next_model": {"answers": ["this is not json", GOOD]},
    "empty_answer_then_next_model": {"answers": ["", GOOD]},
    "fenced_json": {"answers": ["```json\n" + json.dumps(GOOD) + "\n```"]},
    "json_list_not_object": {"answers": ["[1, 2, 3]", GOOD]},
    "zero_clips_then_next_model": {"answers": [EMPTY, GOOD]},
    "zero_clips_everywhere_backup_clips": {"metadata": meta(heatmap=HEATMAP), "answers": [EMPTY]},
    "zero_clips_everywhere_no_summary_title": {"answers": [{"summary": "", "clips": []}],
                                               "body": {"duration": "60s"}},
    "parsed_object_answer": {"answers": [("parsed", GOOD)]},
    "slow_answer_keeps_the_stream_alive": {"answers": [("slow", GOOD)]},
    # --- finishing clips ---
    "hook_outside_clip": {"answers": [{"summary": "s", "clips": [clip(10, 40, hook=99), clip(60, 90, hook=None)]}]},
    "hook_missing": {"answers": [{"summary": "s", "clips": [{k: v for k, v in clip(10, 40).items()
                                                              if k != "hook_time"}]}]},
    "times_as_text": {"answers": [{"summary": "s", "clips": [clip("10", "40", hook=12)]}]},
    "times_unreadable": {"answers": [{"summary": "s", "clips": [clip("abc", None, hook=0)]}]},
    "hook_as_text_breaks_stream": {"answers": [{"summary": "s", "clips": [clip(10, 40, hook="12")]}]},
    "score_null_breaks_stream": {"answers": [{"summary": "s", "clips": [clip(10, 40, score=None)]}]},
    "first_person_titles": {"answers": [{"summary": "s", "clips": [clip(10, 40, title_options=[
        {"text": "Saya Mencoba Lari Tiap Hari"}, {"text": "Aku Menyesal Makan Gorengan"}])]}]},
    "no_title_options": {"answers": [{"summary": "s", "clips": [clip(10, 40, title_options=[],
                                                                     title="Why I Quit Sugar")]}]},
    "overlapping_clips": {"answers": [{"summary": "s", "clips": [clip(10, 50), clip(30, 70), clip(10, 50)]}]},
    # --- demo mode ---
    "mock_mode": {"mock": True, "key": None},
    "mock_mode_bad_url": {"mock": True, "key": None, "body": {"url": "not a url"}},
    # --- stored transcripts with recorded Gemini answers ---
    "stored_komedi_30s": stored("komedi_qedBB492cQY", "30s"),
    "stored_komedi_30s_parsed": stored("komedi_qedBB492cQY", "30s", parsed=True),
    "stored_kesehatan_60s": stored("kesehatan_YGjXfLsuG8k", "60s"),
    "stored_debat_180s": stored("debat_Mwmex7kDaaE", "180s"),
}


# --- running a scenario -----------------------------------------------------------------

def compact(event):
    """Long transcripts in a result are kept as a hash, the rest as is."""
    result = event.get("result")
    if result and len(result.get("transcript") or []) > 60:
        text = json.dumps(result["transcript"], ensure_ascii=False, sort_keys=True)
        event = {**event, "result": {**result, "transcript": {"lines": len(result["transcript"]),
                                                              "sha256": sha(text)}}}
    return event


def run(name, monkeypatch):
    sc = SCENARIOS[name]
    FakeGemini.list_result = sc.get("list_result", [])
    FakeGemini.answers = sc.get("answers", [GOOD])
    FakeGemini.calls = []
    FakeGemini.release = threading.Event()
    sleeps = []

    monkeypatch.setattr(routes_analyze.genai, "Client", FakeGemini)
    monkeypatch.setattr(routes_analyze, "asyncio", FastAsyncio(sleeps))
    if sc.get("discover", True):
        monkeypatch.setattr(routes_analyze, "get_flash_models_for_key", lambda client: [])
    metadata = sc.get("metadata", meta())
    monkeypatch.setattr(routes_analyze, "fetch_video_metadata",
                        raise_(metadata) if isinstance(metadata, Exception) else lambda *a, **k: dict(metadata))
    transcript = sc.get("transcript", lines(24))
    if isinstance(transcript, Exception):
        transcript = raise_(transcript)
    elif not callable(transcript):
        transcript = (lambda t: lambda *a, **k: [dict(x) for x in t])(transcript)
    monkeypatch.setattr(routes_analyze, "fetch_transcript", transcript)
    monkeypatch.setattr(routes_analyze, "get_supadata_keys", lambda: [])
    monkeypatch.setattr(youtube_errors, "block_memory", youtube_errors.BlockMemory(clock=lambda: 1000.0))
    if sc.get("blocked"):
        youtube_errors.block_memory.remember()
    if sc.get("mock"):
        monkeypatch.setenv("MOCK_MODE", "1")
    else:
        monkeypatch.delenv("MOCK_MODE", raising=False)

    body = {"url": URL, "duration": "30s", **sc.get("body", {})}
    request = routes_analyze.AnalyzeRequest(**body)
    logger = logging.getLogger("xoraclips")
    recorder = Recorder()
    old_level = logger.level
    logger.addHandler(recorder)
    logger.setLevel(logging.INFO)

    async def collect():
        response = await routes_analyze.analyze_video(request, sc.get("key", KEY))
        events, crash = [], None
        try:
            async for chunk in response.body_iterator:
                assert chunk.startswith("data: ") and chunk.endswith("\n\n"), chunk
                events.append(compact(json.loads(chunk[6:])))
        except Exception as e:  # the stream broke off: record how
            crash = f"{type(e).__name__}"
        return events, crash

    try:
        events, crash = asyncio.run(collect())
    finally:
        logger.removeHandler(recorder)
        logger.setLevel(old_level)
    return {"events": events, "crash": crash, "gemini_calls": FakeGemini.calls, "sleeps": sleeps,
            "logs": recorder.lines}


def load_snapshot():
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_stream_matches_the_snapshot(name, monkeypatch):
    got = run(name, monkeypatch)
    want = load_snapshot()[name]
    for part in ("events", "crash", "gemini_calls", "sleeps", "logs"):
        assert got[part] == want[part], f"{name}: {part} changed"


def test_every_scenario_is_in_the_snapshot():
    assert sorted(load_snapshot()) == sorted(SCENARIOS)


def test_the_key_never_appears_in_an_event_or_log(monkeypatch):
    for name in ("success_first_try", "bad_key_during_analysis", "key_invalid_upfront"):
        assert KEY not in json.dumps(run(name, monkeypatch), ensure_ascii=False)


if __name__ == "__main__":
    # Regenerate the snapshot from the current code.
    mp = pytest.MonkeyPatch()
    snapshot = {}
    try:
        for scenario in sorted(SCENARIOS):
            snapshot[scenario] = run(scenario, mp)
            mp.undo()
    finally:
        mp.undo()
    SNAPSHOT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {len(snapshot)} scenarios to {SNAPSHOT}")
