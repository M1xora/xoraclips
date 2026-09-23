"""
Issue #10: a download without a video track is rejected, retried once, and
reported in plain words instead of passed on to the render.

Uses the ffprobe output recorded on 2026-09-23 (tests/fixtures/download).
yt-dlp, ffmpeg and ffprobe are fakes: nothing here downloads anything.
"""
import subprocess
from pathlib import Path

import pytest

import video_engine
from video_engine import (
    AUDIO_ONLY_MESSAGE,
    AUDIO_ONLY_RETRY_DELAY,
    FORMAT_720,
    FORMAT_1080,
    RETRY_TIMEOUT_SECONDS,
    download_clip_segment,
    streams_have_video,
    worst_case_download_seconds,
)

FIXTURES = Path(__file__).parent / "fixtures" / "download"
AUDIO_ONLY = (FIXTURES / "ffprobe_audio_only.json").read_text(encoding="utf-8")
VIDEO_AUDIO = (FIXTURES / "ffprobe_video_audio.json").read_text(encoding="utf-8")


def test_recorded_audio_only_file_has_no_video():
    assert streams_have_video(AUDIO_ONLY) is False


def test_recorded_normal_file_has_video():
    assert streams_have_video(VIDEO_AUDIO) is True


def test_unreadable_ffprobe_output_is_not_video():
    assert streams_have_video("not json") is False
    assert streams_have_video("") is False


def test_every_format_choice_demands_a_video_codec():
    """A bare `best` takes an audio format whose video codec is not stated."""
    for selector in (FORMAT_1080, FORMAT_720):
        for alternative in selector.split("/"):
            assert "+" in alternative or "vcodec!=none" in alternative, alternative


def test_worst_case_wait_is_bounded():
    # 60s clip: the three methods' timeouts (unchanged), plus one audio-only
    # retry: a quick rejection (60) + pause (8) + stream URLs (45) + short retry (90).
    assert worst_case_download_seconds(60) == {"before": 915, "after": 915 + 203}
    assert worst_case_download_seconds(15) == {"before": 645, "after": 645 + 203}


class FakeTools:
    """
    Plays yt-dlp, ffmpeg and ffprobe. `outcomes` says what each download
    writes, in order: "video", "audio" or None (nothing).
    """

    def __init__(self, outcomes, seconds_per_download=5.0):
        self.outcomes = list(outcomes)
        self.seconds_per_download = seconds_per_download
        self.now = 0.0
        self.calls = []

    def clock(self):
        return self.now

    def _write(self, path):
        outcome = self.outcomes.pop(0) if self.outcomes else None
        self.now += self.seconds_per_download
        if outcome:
            Path(path).write_bytes(outcome.upper().encode() * 5000)

    def run(self, cmd, **kwargs):
        tool = cmd[0]
        if tool == "ffprobe":
            data = Path(cmd[-1]).read_bytes()[:5]
            out = VIDEO_AUDIO if data == b"VIDEO" else AUDIO_ONLY
            return subprocess.CompletedProcess(cmd, 0, out, "")
        if tool == "yt-dlp" and "-g" in cmd:
            self.calls.append(("urls", kwargs.get("timeout")))
            return subprocess.CompletedProcess(cmd, 0, "https://v.example\nhttps://a.example\n", "")
        if tool == "yt-dlp":
            method = "720p" if FORMAT_720 in cmd else "hd"
            self.calls.append((method, kwargs.get("timeout")))
            self._write(cmd[cmd.index("-o") + 1])
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if tool == "ffmpeg":
            self.calls.append(("trim", kwargs.get("timeout")))
            self._write(cmd[-1])
            return subprocess.CompletedProcess(cmd, 0, b"", b"")
        raise AssertionError(f"unexpected command {cmd}")


@pytest.fixture
def tools(monkeypatch, tmp_path):
    def make(outcomes, **kwargs):
        fake = FakeTools(outcomes, **kwargs)
        monkeypatch.setattr(video_engine, "TEMP_DIR", tmp_path)
        monkeypatch.setattr(video_engine, "get_yt_dlp_base_cmd", lambda: ["yt-dlp"])
        monkeypatch.setattr(video_engine.subprocess, "run", fake.run)
        return fake
    return make


def download(fake, notes=None, sleeps=None):
    return download_clip_segment(
        "dQw4w9WgXcQ", 60.0, 85.0, "clip.mp4",
        on_status=(notes.append if notes is not None else None),
        sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
        clock=fake.clock,
    )


def test_a_normal_download_is_used_at_once(tools):
    fake = tools(["video"])
    notes, sleeps = [], []
    path = download(fake, notes, sleeps)
    assert Path(path).read_bytes()[:5] == b"VIDEO"
    assert [c[0] for c in fake.calls] == ["hd"]
    assert notes == [] and sleeps == []


def test_audio_only_is_retried_once_after_a_pause_and_then_used(tools):
    fake = tools(["audio", "video"])
    notes, sleeps = [], []
    path = download(fake, notes, sleeps)
    assert Path(path).read_bytes()[:5] == b"VIDEO"
    assert [c[0] for c in fake.calls] == ["hd", "hd"]
    assert sleeps == [AUDIO_ONLY_RETRY_DELAY]
    assert notes == [{"code": "audio_only_retry", "method": 1, "methods": 3, "wait": AUDIO_ONLY_RETRY_DELAY}]
    assert fake.calls[1][1] == RETRY_TIMEOUT_SECONDS  # the retry is short


def test_audio_only_everywhere_ends_in_a_clear_message(tools, tmp_path):
    fake = tools(["audio"] * 10)
    notes, sleeps = [], []
    with pytest.raises(RuntimeError) as caught:
        download(fake, notes, sleeps)
    assert str(caught.value) == AUDIO_ONLY_MESSAGE
    # One retry for the whole clip, then each other method once.
    assert [c[0] for c in fake.calls] == ["hd", "hd", "urls", "trim", "720p"]
    assert sleeps == [AUDIO_ONLY_RETRY_DELAY]
    assert [n["code"] for n in notes] == ["audio_only_retry", "next_method", "next_method"]
    assert not (tmp_path / "clip.mp4").exists()  # rejected files are deleted


def test_a_slow_rejection_is_not_retried(tools):
    fake = tools(["audio", "video"], seconds_per_download=120.0)
    notes, sleeps = [], []
    download(fake, notes, sleeps)
    assert [c[0] for c in fake.calls] == ["hd", "urls", "trim"]
    assert sleeps == []
    assert notes == [{"code": "next_method", "method": 2, "methods": 3}]


def test_file_is_kept_when_ffprobe_cannot_run(tools, monkeypatch):
    fake = tools(["audio"])
    real_run = fake.run

    def no_ffprobe(cmd, **kwargs):
        if cmd[0] == "ffprobe":
            raise FileNotFoundError("ffprobe")
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(video_engine.subprocess, "run", no_ffprobe)
    assert Path(download(fake)).exists()


def test_bot_check_still_wins_over_audio_only(tools, monkeypatch):
    fake = tools(["audio"] * 10)
    real_run = fake.run

    def bot(cmd, **kwargs):
        res = real_run(cmd, **kwargs)
        if cmd[0] == "yt-dlp" and "-g" not in cmd:
            res.stderr = "ERROR: Sign in to confirm you're not a bot"
        return res

    monkeypatch.setattr(video_engine.subprocess, "run", bot)
    with pytest.raises(RuntimeError, match="Bot verification"):
        download(fake)


# --- yt-dlp's own format selector, offline ------------------------------------------

OLD_FORMAT = "bestvideo[height<=1080]+bestaudio/best[height<=1080]/bestvideo+bestaudio/best"


def picks(selector, formats):
    yt_dlp = pytest.importorskip("yt_dlp")
    with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
        chosen = ydl.build_format_selector(selector)(
            {"formats": formats, "has_merged_format": False, "incomplete_formats": False}
        )
        return [f.get("format_id") for f in chosen]


def fmt(fid, height=None, ext="mp4", **codecs):
    return {"format_id": fid, "height": height, "ext": ext, "url": f"https://x/{fid}",
            "protocol": "https", "tbr": (height or 1) * 10, **codecs}


def test_normal_formats_are_chosen_as_before():
    formats = [fmt("140", None, "m4a", vcodec="none", acodec="mp4a"),
               fmt("137", 1080, vcodec="avc1", acodec="none"),
               fmt("18", 360, vcodec="avc1", acodec="mp4a")]
    assert picks(OLD_FORMAT, formats) == picks(FORMAT_1080, formats) == ["137+140"]


def test_audio_without_a_stated_video_codec_is_no_longer_chosen():
    """The old `best` took an audio format whose video codec YouTube did not state."""
    formats = [fmt("140", None, "m4a", acodec="mp4a"), fmt("141", None, "m4a")]
    assert picks(OLD_FORMAT, formats) == ["141"]
    assert picks(FORMAT_1080, formats) == []
    assert picks(FORMAT_720, formats) == []
