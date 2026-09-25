"""
Issue #9: recognise YouTube refusing us, stop every remaining tier, remember
it for a while, and tell the user in one short line.

Uses the block responses recorded on 2026-09-23 (tests/fixtures/youtube_block).
Nothing here reaches the network: YouTube, the CLI, yt-dlp and requests are
fakes, and any real connection attempt fails the test.
"""
import json
import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from youtube_transcript_api._errors import IpBlocked, TranscriptsDisabled

import main
import youtube_source
import youtube_errors
from youtube_errors import BlockMemory, CaptionUnavailable, YouTubeBlocked

FIXTURES = Path(__file__).parent / "fixtures"
CLI_BLOCKED = (FIXTURES / "youtube_block" / "cli_stdout_ipblocked.txt").read_text(encoding="utf-8")
SORRY_PAGE = (FIXTURES / "youtube_block" / "timedtext_429_sorry.html").read_text(encoding="utf-8")
API_BLOCKED = (FIXTURES / "youtube_block" / "python_api_ipblocked.txt").read_text(encoding="utf-8")
NORMAL_CAPTIONS = (FIXTURES / "ted_manual_captions.json").read_text(encoding="utf-8")
VIDEO = "rBg0ZcwjVKQ"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Only loopback is allowed (asyncio on Windows talks to itself over it)."""
    real_connect = socket.socket.connect

    def guarded(sock, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"a test tried to reach the network: {address}")
        return real_connect(sock, address, *args, **kwargs)

    def refuse(address, *args, **kwargs):
        raise AssertionError(f"a test tried to reach the network: {address}")

    monkeypatch.setattr(socket.socket, "connect", guarded)
    monkeypatch.setattr(socket, "create_connection", refuse)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


# --- recognising a block ----------------------------------------------------------

def test_recorded_cli_output_is_a_block():
    assert youtube_errors.is_blocked_text(CLI_BLOCKED)


def test_recorded_sorry_page_is_a_block():
    assert youtube_errors.is_blocked_response(429, "text/html; charset=UTF-8", SORRY_PAGE)
    # The same page with another status still means "refused".
    assert youtube_errors.is_blocked_response(200, "text/html; charset=UTF-8", SORRY_PAGE)


def test_recorded_python_api_error_is_a_block():
    assert youtube_errors.is_blocked_exception(Exception(API_BLOCKED))
    assert youtube_errors.is_blocked_exception(IpBlocked(VIDEO))


def test_bot_check_is_a_block():
    err = Exception("ERROR: [youtube] rBg0ZcwjVKQ: Sign in to confirm you're not a bot.")
    assert youtube_errors.is_blocked_exception(err)


def test_normal_answers_are_not_blocks():
    assert not youtube_errors.is_blocked_response(200, "application/json", NORMAL_CAPTIONS)
    assert not youtube_errors.is_blocked_response(404, "text/html", "<title>Not Found</title>")
    assert not youtube_errors.is_blocked_exception(TranscriptsDisabled(VIDEO))
    assert not youtube_errors.is_blocked_exception(Exception("No transcripts were found"))


def test_block_memory_counts_down_and_expires():
    clock = Clock()
    memory = BlockMemory(seconds=600, clock=clock)
    assert memory.remaining() == 0
    memory.remember()
    clock.now += 30
    assert memory.remaining() == 570
    clock.now += 571
    assert memory.remaining() == 0


# --- stopping the tiers -------------------------------------------------------------

class Script:
    """What each fake YouTube path does, and a log of every call to YouTube."""

    def __init__(self):
        self.calls = []
        self.api_fetch_error = Exception("No transcripts were found for any of the requested language codes")
        self.api_list_error = None
        self.tracks = []
        self.cli = (0, "[]", "")
        self.ydl_error = None
        self.ydl_info = {"subtitles": {}, "automatic_captions": {}}
        self.http = lambda url: FakeResponse(404, "text/html", "<title>Not Found</title>")


class FakeResponse:
    def __init__(self, status, content_type, text):
        self.status_code = status
        self.headers = {"content-type": content_type}
        self.text = text

    def json(self):
        return json.loads(self.text)


class FakeTrack:
    def __init__(self, script, language, error):
        self.script, self.language, self.error = script, language, error
        self.is_generated = True
        self.is_translatable = False

    def fetch(self):
        self.script.calls.append(f"track:{self.language}")
        raise self.error


def install_fakes(monkeypatch, script):
    class FakeApi:
        def __init__(self, *args, **kwargs):
            pass

        def fetch(self, video_id, languages=None):
            script.calls.append("api.fetch")
            raise script.api_fetch_error

        def list(self, video_id):
            script.calls.append("api.list")
            if script.api_list_error:
                raise script.api_list_error
            return script.tracks

    class FakeClient:
        cookies = {}

    class FakeYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=False):
            script.calls.append("ytdlp.info")
            if script.ydl_error:
                raise script.ydl_error
            return script.ydl_info

    class Proc:
        def __init__(self, code, out, err):
            self.returncode, self.stdout, self.stderr = code, out, err

    def fake_run(cmd, **kwargs):
        script.calls.append("cli")
        return Proc(*script.cli)

    def fake_get(url, **kwargs):
        script.calls.append(f"get:{url}")
        return script.http(url)

    monkeypatch.setattr(youtube_source, "YouTubeTranscriptApi", FakeApi)
    monkeypatch.setattr(youtube_source, "create_http_client", lambda **kw: FakeClient())
    monkeypatch.setattr(youtube_source.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(youtube_source.subprocess, "run", fake_run)
    monkeypatch.setattr(youtube_source.requests, "get", fake_get)
    monkeypatch.setattr(youtube_source, "get_supadata_keys", lambda: [])
    monkeypatch.setattr(youtube_source, "get_proxy_url", lambda: None)
    monkeypatch.setattr(youtube_source, "get_youtube_transcript_proxy_config", lambda *a, **k: None)


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(youtube_errors, "block_memory", BlockMemory(seconds=600, clock=clock))
    return clock


@pytest.fixture
def script(monkeypatch, clock):
    s = Script()
    install_fakes(monkeypatch, s)
    return s


def many_languages(n=159):
    auto = {f"l{i}": [{"ext": "json3", "url": f"https://yt/l{i}"}] for i in range(n)}
    auto["id-orig"] = [{"ext": "json3", "url": "https://yt/id-orig"}]
    auto["id"] = [{"ext": "json3", "url": "https://yt/id"}]
    auto["en"] = [{"ext": "json3", "url": "https://yt/en"}]
    return {"subtitles": {}, "automatic_captions": auto}


def test_python_api_block_stops_everything(script):
    script.api_fetch_error = IpBlocked(VIDEO)
    with pytest.raises(YouTubeBlocked) as caught:
        youtube_source.fetch_transcript(VIDEO)
    assert script.calls == ["api.fetch"]
    assert caught.value.retry_after == 600


def test_block_on_one_track_stops_the_other_tracks(script):
    script.tracks = [FakeTrack(script, "id", IpBlocked(VIDEO)), FakeTrack(script, "en", IpBlocked(VIDEO))]
    with pytest.raises(YouTubeBlocked):
        youtube_source.fetch_transcript(VIDEO)
    assert script.calls == ["api.fetch", "api.list", "track:id"]


def test_cli_block_printed_with_exit_code_zero_stops_yt_dlp(script):
    script.cli = (0, CLI_BLOCKED, "")
    with pytest.raises(YouTubeBlocked):
        youtube_source.fetch_transcript(VIDEO)
    assert "ytdlp.info" not in script.calls
    assert script.calls[-1] == "cli"


def test_cli_output_that_is_not_json_is_reported_as_it_is(script):
    script.cli = (0, "\nSomething else went wrong in the CLI\n", "")
    with pytest.raises(CaptionUnavailable) as caught:
        youtube_source.fetch_transcript(VIDEO)
    assert "Something else went wrong in the CLI" in caught.value.detail
    assert "JSONDecodeError" not in caught.value.detail


def test_yt_dlp_asks_once_when_blocked_even_with_159_languages(script):
    script.ydl_info = many_languages()
    script.http = lambda url: FakeResponse(429, "text/html; charset=UTF-8", SORRY_PAGE)
    with pytest.raises(YouTubeBlocked):
        youtube_source.fetch_transcript(VIDEO)
    assert [c for c in script.calls if c.startswith("get:")] == ["get:https://yt/id-orig"]


def test_yt_dlp_asks_at_most_three_times_without_a_block(script):
    script.ydl_info = many_languages()
    with pytest.raises(CaptionUnavailable) as caught:
        youtube_source.fetch_transcript(VIDEO)
    assert caught.value.code == youtube_errors.CAPTIONS_UNAVAILABLE
    assert len([c for c in script.calls if c.startswith("get:")]) == 3


def test_yt_dlp_bot_check_is_a_block(script):
    script.ydl_error = Exception("ERROR: [youtube] x: Sign in to confirm you're not a bot.")
    with pytest.raises(YouTubeBlocked):
        youtube_source.fetch_transcript(VIDEO)


def test_caption_candidates_order():
    subtitles = {"ja": [{"ext": "json3", "url": "u-ja"}], "en-US": [{"ext": "json3", "url": "u-en-man"}]}
    auto = many_languages(20)["automatic_captions"]
    picked = youtube_source.ytdlp_caption_candidates(subtitles, auto)
    assert [(lang, is_auto) for lang, is_auto, _ in picked] == [("en-US", False), ("ja", False), ("id-orig", True)]


def test_a_human_track_in_another_language_is_still_tried():
    subtitles = {"ja": [{"ext": "json3", "url": "u-ja"}]}
    picked = youtube_source.ytdlp_caption_candidates(subtitles, {})
    assert [(lang, is_auto) for lang, is_auto, _ in picked] == [("ja", False)]


def test_proxy_wording_of_the_block_is_recognised():
    text = "YouTube is blocking your requests, despite you using proxies. Keep in mind..."
    assert youtube_errors.is_blocked_text(text)


def test_a_users_own_proxy_being_refused_does_not_lock_everyone_out(script):
    script.api_fetch_error = IpBlocked(VIDEO)
    with pytest.raises(YouTubeBlocked) as caught:
        youtube_source.fetch_transcript(VIDEO, custom_proxy="http://user-proxy:8080")
    assert caught.value.retry_after == 0
    assert youtube_errors.block_memory.remaining() == 0


def test_a_block_found_by_another_analysis_stops_this_one_between_tiers(script):
    # Tier 5 fails normally, but meanwhile another analysis was refused.
    def list_then_block(video_id):
        script.calls.append("api.list")
        youtube_errors.block_memory.remember()
        raise Exception("No transcripts were found")
    youtube_source.YouTubeTranscriptApi.list = lambda self, video_id: list_then_block(video_id)
    with pytest.raises(YouTubeBlocked):
        youtube_source.fetch_transcript(VIDEO)
    assert "cli" not in script.calls and "ytdlp.info" not in script.calls


def test_a_block_seen_while_reading_video_details_is_remembered(script, monkeypatch):
    script.ydl_error = Exception("ERROR: [youtube] x: Sign in to confirm you're not a bot.")
    monkeypatch.setattr(youtube_source, "get_youtube_oembed_title", lambda *a, **k: None)
    youtube_source.fetch_video_metadata(f"https://www.youtube.com/watch?v={VIDEO}")
    assert youtube_errors.block_memory.remaining() == 600


def test_a_block_is_remembered_and_youtube_is_left_alone(script, clock):
    script.api_fetch_error = IpBlocked(VIDEO)
    with pytest.raises(YouTubeBlocked):
        youtube_source.fetch_transcript(VIDEO)
    calls_after_block = list(script.calls)

    clock.now += 60
    with pytest.raises(YouTubeBlocked) as again:
        youtube_source.fetch_transcript(VIDEO)
    assert script.calls == calls_after_block  # nothing sent to YouTube
    assert again.value.retry_after == 540

    clock.now += 541  # the wait is over: YouTube is tried again
    with pytest.raises(YouTubeBlocked):
        youtube_source.fetch_transcript(VIDEO)
    assert len(script.calls) > len(calls_after_block)


def test_supadata_still_works_while_youtube_is_remembered_as_blocked(script, monkeypatch):
    youtube_errors.block_memory.remember()
    monkeypatch.setattr(youtube_source, "get_supadata_keys", lambda: ["sd_test"])
    monkeypatch.setattr(youtube_source, "fetch_transcript_supadata", lambda *a, **k: [{"text": "halo", "start": 0.0, "duration": 1.0}])
    assert youtube_source.fetch_transcript(VIDEO)[0]["text"] == "halo"
    assert script.calls == []


def test_captions_turned_off_gets_its_own_code(script):
    script.api_fetch_error = TranscriptsDisabled(VIDEO)
    script.api_list_error = TranscriptsDisabled(VIDEO)
    with pytest.raises(CaptionUnavailable) as caught:
        youtube_source.fetch_transcript(VIDEO)
    assert caught.value.code == youtube_errors.CAPTIONS_DISABLED


# --- what the user sees -------------------------------------------------------------

class FakeGemini:
    def __init__(self, *args, **kwargs):
        self.models = self

    def list(self, *args, **kwargs):
        return []

    def generate_content(self, *args, **kwargs):
        raise RuntimeError("503 UNAVAILABLE")


def metadata(live=False):
    return lambda *a, **k: {
        "title": "Uji", "channel": "Kanal", "duration": 120.0, "heatmap": [],
        "is_live": live, "live_status": "is_live" if live else "not_live",
    }


def no_youtube(*args, **kwargs):
    raise AssertionError("YouTube must not be contacted")


class InstantAsyncio:
    """main.py's asyncio with retry back-off made instant."""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    @staticmethod
    async def sleep(*args, **kwargs):
        return None


@pytest.fixture
def api(monkeypatch, clock):
    monkeypatch.setattr(main, "asyncio", InstantAsyncio(main.asyncio))
    monkeypatch.setattr(main.time, "sleep", lambda *_: None)
    monkeypatch.setattr(main.genai, "Client", FakeGemini)
    monkeypatch.setattr(main, "fetch_video_metadata", metadata())
    monkeypatch.setattr(main, "get_supadata_keys", lambda: [])
    monkeypatch.delenv("MOCK_MODE", raising=False)
    return TestClient(main.app)


def analyze(api, **extra):
    body = {"url": f"https://www.youtube.com/watch?v={VIDEO}", "model": "gemini-2.5-flash", **extra}
    res = api.post("/api/analyze", json=body, headers={"X-Gemini-Api-Key": "AIzaSyFAKE_USER_KEY_0123456789abcdefgh"})
    events = [json.loads(line[5:]) for line in res.text.splitlines() if line.startswith("data:")]
    return [e for e in events if "error" in e], res.text


def raising(error):
    def fetch(*args, **kwargs):
        raise error
    return fetch


def test_blocked_analysis_shows_one_short_line_and_when_to_retry(api, monkeypatch):
    blocked = YouTubeBlocked("Tier 5a: IpBlocked (...)", retry_after=600)
    monkeypatch.setattr(main, "fetch_transcript", raising(blocked))
    errors, text = analyze(api)
    assert errors == [{
        "error": youtube_errors.MESSAGES["youtube_blocked"],
        "code": "youtube_blocked", "status": 429, "retry_after": 600,
    }]
    assert "Tier" not in text


def test_remembered_block_answers_before_touching_youtube(api, monkeypatch, clock):
    youtube_errors.block_memory.remember()
    clock.now += 100
    monkeypatch.setattr(main, "fetch_video_metadata", no_youtube)
    monkeypatch.setattr(main, "fetch_transcript", no_youtube)
    errors, _ = analyze(api)
    assert [(e["code"], e["retry_after"]) for e in errors] == [("youtube_blocked", 500)]


def test_an_invalid_link_is_still_called_invalid_during_a_block(api):
    youtube_errors.block_memory.remember()
    errors, _ = analyze(api, url="https://example.com/foo")
    assert errors[0].get("code") != "youtube_blocked"
    assert "Invalid YouTube URL" in errors[0]["error"]


def test_manual_subtitles_still_work_during_a_remembered_block(api, monkeypatch):
    youtube_errors.block_memory.remember()
    monkeypatch.setattr(main, "fetch_transcript", no_youtube)
    srt = "1\n00:00:01,000 --> 00:00:04,000\nhalo semua\n\n2\n00:00:05,000 --> 00:00:08,000\napa kabar\n"
    errors, _ = analyze(api, subtitles=srt, subtitles_filename="x.srt")
    assert "youtube_blocked" not in [e.get("code") for e in errors]


def test_a_block_beats_the_live_video_message(api, monkeypatch):
    monkeypatch.setattr(main, "fetch_video_metadata", metadata(live=True))
    monkeypatch.setattr(main, "fetch_transcript", raising(YouTubeBlocked("x", retry_after=600)))
    errors, _ = analyze(api)
    assert errors[0]["code"] == "youtube_blocked"


@pytest.mark.parametrize("error, code", [
    (CaptionUnavailable("captions_disabled", "Tier 5 (Direct Python API): TranscriptsDisabled (...)"), "captions_disabled"),
    (CaptionUnavailable("video_unavailable", "Tier 5: VideoUnavailable"), "video_unavailable"),
    (RuntimeError("Traceback-ish internal detail /home/x/secret/path"), "captions_unavailable"),
])
def test_other_caption_failures_are_short_too(api, monkeypatch, error, code):
    monkeypatch.setattr(main, "fetch_transcript", raising(error))
    errors, text = analyze(api)
    assert [e["code"] for e in errors] == [code]
    assert errors[0]["error"] == youtube_errors.MESSAGES[code]
    assert "Tier" not in text and "/home/x" not in text


def test_live_video_without_captions_gets_its_code(api, monkeypatch):
    monkeypatch.setattr(main, "fetch_video_metadata", metadata(live=True))
    monkeypatch.setattr(main, "fetch_transcript", raising(CaptionUnavailable("captions_unavailable", "x")))
    errors, _ = analyze(api)
    assert errors[0]["code"] == "video_live"
