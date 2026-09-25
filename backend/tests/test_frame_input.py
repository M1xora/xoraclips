"""
Issue #42: text from the browser never reaches a yt-dlp command line as-is.

/api/clip-frame and /api/detect-face take only a valid video ID and build the
YouTube URL themselves; every yt-dlp command ends with "--" and the URL, so
the URL can never be read as an option. yt-dlp, ffmpeg and the network are
fakes: nothing here downloads anything.
"""
import io
import subprocess

import pytest
from fastapi.testclient import TestClient

import main
import video_engine

VALID_ID = "dQw4w9WgXcQ"
BAD_IDS = [
    "abc",               # too short
    "dQw4w9WgXcQ1",      # too long
    "dQw4w9WgXc!",       # a character a YouTube ID never has
    "dQw4w9WgXc\n",      # 11 characters, but the last one is a line break
    "https://youtu.be",  # a URL is not an ID
]


@pytest.fixture
def frame_calls(monkeypatch, tmp_path):
    """Records what the endpoints hand to extract_clip_frame (which does nothing).
    Empty folders, so detect-face never finds a real video on this machine."""
    calls = []

    def fake_extract(*args):
        calls.append(args)
        return None

    monkeypatch.setattr(main, "extract_clip_frame", fake_extract)
    monkeypatch.setattr(main, "TEMP_DIR", tmp_path)
    monkeypatch.setattr(main, "EXPORTS_DIR", tmp_path)
    return calls


@pytest.mark.parametrize("path", ["/api/clip-frame", "/api/detect-face"])
@pytest.mark.parametrize("bad_id", BAD_IDS)
def test_an_invalid_video_id_is_refused(frame_calls, path, bad_id):
    res = TestClient(main.app).get(path, params={"video_id": bad_id})
    assert res.status_code == 400
    assert frame_calls == []


@pytest.mark.parametrize("path", ["/api/clip-frame", "/api/detect-face"])
def test_a_video_url_from_the_browser_is_ignored(frame_calls, path):
    TestClient(main.app).get(
        path, params={"video_id": VALID_ID, "timestamp": 12, "video_url": "anything-at-all"}
    )
    assert frame_calls == [(VALID_ID, 12.0)]


@pytest.mark.parametrize("path", ["/api/clip-frame", "/api/detect-face"])
@pytest.mark.parametrize("timestamp", ["inf", "nan", "-1", "90000"])
def test_a_timestamp_outside_0_to_24_hours_is_refused(frame_calls, path, timestamp):
    res = TestClient(main.app).get(path, params={"video_id": VALID_ID, "timestamp": timestamp})
    assert res.status_code == 422
    assert frame_calls == []


@pytest.fixture
def ytdlp_commands(monkeypatch, tmp_path):
    """Fakes yt-dlp, ffmpeg and the network; returns every yt-dlp command run."""
    commands = []

    def fake_run(cmd, *args, **kwargs):
        if cmd[0] == "yt-dlp":
            commands.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="fake failure")

    class FakePopen:
        def __init__(self, cmd, *args, **kwargs):
            if cmd[0] == "yt-dlp":
                commands.append(list(cmd))
            self.stdout = io.StringIO("")

        def wait(self):
            return 1

    def no_network(*args, **kwargs):
        raise OSError("no network in tests")

    monkeypatch.setattr(video_engine, "TEMP_DIR", tmp_path)
    monkeypatch.setattr(video_engine, "EXPORTS_DIR", tmp_path / "exports")
    monkeypatch.setattr(video_engine, "get_yt_dlp_base_cmd", lambda: ["yt-dlp"])
    monkeypatch.setattr(video_engine.subprocess, "run", fake_run)
    monkeypatch.setattr(video_engine.subprocess, "Popen", FakePopen)
    monkeypatch.setattr("urllib.request.urlopen", no_network)
    return commands


def assert_url_is_last_after_separator(cmd, url):
    assert cmd[-2:] == ["--", url], cmd


def test_frame_extraction_builds_the_url_from_the_id(ytdlp_commands):
    video_engine.extract_clip_frame(VALID_ID, 5.0)
    assert len(ytdlp_commands) == 1
    assert_url_is_last_after_separator(
        ytdlp_commands[0], f"https://www.youtube.com/watch?v={VALID_ID}")


@pytest.mark.parametrize("bad_id", BAD_IDS)
def test_frame_extraction_itself_refuses_a_bad_id(ytdlp_commands, bad_id):
    # Safe even for a future caller that forgets require_video_id.
    assert video_engine.extract_clip_frame(bad_id, 5.0) is None
    assert ytdlp_commands == []


def test_an_id_that_looks_like_an_option_stays_inside_the_url(ytdlp_commands):
    # 11 allowed characters, so it passes the ID check: the built URL and
    # the "--" separator are what keep it from being read as an option.
    video_engine.extract_clip_frame("--abcdefghi", 5.0)
    assert_url_is_last_after_separator(
        ytdlp_commands[0], "https://www.youtube.com/watch?v=--abcdefghi")


def test_every_clip_download_method_ends_with_the_separator(ytdlp_commands):
    url = f"https://www.youtube.com/watch?v={VALID_ID}"
    with pytest.raises(RuntimeError):
        video_engine.download_clip_segment(
            url, 10.0, 20.0, "clip.mp4", sleep=lambda _: None)
    # Method 1 (HD section), method 2 (stream URLs), method 3 (720p section).
    assert len(ytdlp_commands) == 3
    for cmd in ytdlp_commands:
        assert_url_is_last_after_separator(cmd, url)


def test_full_video_download_ends_with_the_separator(ytdlp_commands, tmp_path):
    url = f"https://www.youtube.com/watch?v={VALID_ID}"
    with pytest.raises(RuntimeError):
        video_engine.download_full_raw_video(url, str(tmp_path / "full.mp4"))
    assert len(ytdlp_commands) == 1
    assert_url_is_last_after_separator(ytdlp_commands[0], url)
