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

    def fake_extract_info(*args):
        calls.append(args)
        return None, False

    monkeypatch.setattr(main, "extract_clip_frame", fake_extract)
    monkeypatch.setattr(main, "extract_clip_frame_info", fake_extract_info)
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
    monkeypatch.setattr(video_engine, "_frame_failures", {})
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


# --- Issue #44: real frames again, and a stand-in is never cached as one ---

def test_frame_extraction_does_not_ask_for_format_18(ytdlp_commands):
    video_engine.extract_clip_frame(VALID_ID, 5.0)
    cmd = ytdlp_commands[0]
    assert cmd[cmd.index("-f") + 1] == video_engine.FRAME_FORMAT == "bv*/b"  # video-only is enough
    assert "18" not in cmd[cmd.index("-f") + 1]  # YouTube stopped serving format 18
    # "res" is the short side, so a vertical Short is not cut down to 270px wide.
    assert cmd[cmd.index("-S") + 1].startswith("res:480")


class FakeThumbnail:
    """What urllib.request.urlopen returns for i.ytimg.com."""
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b"\xff\xd8" + b"x" * 5000


def test_a_thumbnail_is_a_stand_in_saved_under_its_own_name(ytdlp_commands, monkeypatch, tmp_path):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: FakeThumbnail())
    path, exact = video_engine.extract_clip_frame_info(VALID_ID, 5.0)
    assert path is not None and path.endswith(f"{VALID_ID}_thumb.jpg")
    assert exact is False
    # Not cached as the frame of second 5, so a later try can cut the real one.
    assert not (tmp_path / "frames" / f"{VALID_ID}_5.jpg").exists()


def test_the_nearest_real_frame_of_the_video_is_the_first_stand_in(ytdlp_commands, tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    for sec in (10, 50, 90):
        (frames / f"{VALID_ID}_{sec}.jpg").write_bytes(b"x" * 5000)
    (frames / f"{VALID_ID}_thumb.jpg").write_bytes(b"x" * 5000)
    path, exact = video_engine.extract_clip_frame_info(VALID_ID, 60.0)
    assert path.endswith(f"{VALID_ID}_50.jpg") and exact is False
    assert not (frames / f"{VALID_ID}_60.jpg").exists()


def test_a_cached_frame_is_exact_and_asks_youtube_nothing(ytdlp_commands, tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / f"{VALID_ID}_7.jpg").write_bytes(b"x" * 5000)
    path, exact = video_engine.extract_clip_frame_info(VALID_ID, 7.0)
    assert path.endswith(f"{VALID_ID}_7.jpg") and exact is True
    assert ytdlp_commands == []


def test_a_refused_second_is_not_asked_again_for_a_while(ytdlp_commands):
    now = [1000.0]
    clock = lambda: now[0]
    video_engine.extract_clip_frame_info(VALID_ID, 5.0, clock=clock)
    video_engine.extract_clip_frame_info(VALID_ID, 5.0, clock=clock)
    assert len(ytdlp_commands) == 1
    now[0] += video_engine.FRAME_FAILURE_TTL + 1
    video_engine.extract_clip_frame_info(VALID_ID, 5.0, clock=clock)
    assert len(ytdlp_commands) == 2


def test_each_request_uses_its_own_temporary_slice(ytdlp_commands):
    video_engine.extract_clip_frame_info(VALID_ID, 5.0, clock=lambda: 0.0)
    video_engine.extract_clip_frame_info(VALID_ID, 5.0, clock=lambda: 10_000.0)
    outputs = [cmd[cmd.index("-o") + 1] for cmd in ytdlp_commands]
    assert len(outputs) == 2 and outputs[0] != outputs[1]


def test_a_rendered_clip_on_disk_is_never_used_as_a_frame(monkeypatch, tmp_path):
    # The old step 1 took second 1 of any local mp4 with the ID in its name,
    # renders included, and cached it as the frame of the asked second.
    exports = tmp_path / "exports"
    exports.mkdir()
    (exports / f"clip_1_batch_{VALID_ID}.mp4").write_bytes(b"x" * 20000)
    commands = []
    monkeypatch.setattr(video_engine, "TEMP_DIR", tmp_path)
    monkeypatch.setattr(video_engine, "EXPORTS_DIR", exports)
    monkeypatch.setattr(video_engine, "_frame_failures", {})
    monkeypatch.setattr(video_engine, "get_yt_dlp_base_cmd", lambda: ["yt-dlp"])
    monkeypatch.setattr(video_engine.subprocess, "run",
                        lambda cmd, *a, **k: commands.append(cmd) or subprocess.CompletedProcess(cmd, 1, "", ""))
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    video_engine.extract_clip_frame_info(VALID_ID, 5.0)
    assert not any("clip_1_batch" in " ".join(map(str, cmd)) for cmd in commands)


@pytest.mark.parametrize("exact, cache", [(False, "no-store"), (True, "public, max-age=86400")])
def test_clip_frame_does_not_let_the_browser_keep_a_stand_in(monkeypatch, tmp_path, exact, cache):
    frame = tmp_path / f"{VALID_ID}_12.jpg"
    frame.write_bytes(b"\xff\xd8" + b"x" * 5000)
    monkeypatch.setattr(main, "extract_clip_frame_info", lambda *a: (str(frame), exact))
    res = TestClient(main.app).get("/api/clip-frame", params={"video_id": VALID_ID, "timestamp": 12})
    assert res.status_code == 200
    assert res.headers["cache-control"] == cache
