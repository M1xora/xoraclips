"""
Issue #117: a caption request that is merely slow must not be cut off, and
must not be mistaken for YouTube blocking us.

Measured on a 4.4 hour video (3.3 MB caption track): a healthy request takes
0.6 to 30.5 seconds, so the old 8 second timeout cut off requests that were
going to succeed. Each cut-off made the code ask for the next candidate, and
the repeated asking earned a real 429 that stopped every remaining tier.

Nothing here reaches the network: requests.get is a fake and sleeping is
stubbed out so the tests stay fast.
"""
import json

import pytest
import requests

import youtube_source
from youtube_errors import YouTubeBlocked

CAPTION_URL = "https://www.youtube.com/api/timedtext?v=test&fmt=json3"

CAPTION_JSON = {
    "events": [
        {"tStartMs": 0, "dDurationMs": 1500, "segs": [{"utf8": "halo"}]},
        {"tStartMs": 1500, "dDurationMs": 1500, "segs": [{"utf8": "dunia"}]},
    ]
}


class FakeResponse:
    def __init__(self, status_code=200, payload=None, content_type="application/json"):
        self.status_code = status_code
        self._payload = payload if payload is not None else CAPTION_JSON
        self.headers = {"content-type": content_type}
        self.text = "" if "json" in content_type else "<html>oops</html>"

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch):
    """The pause between requests is real in production, skipped in tests."""
    monkeypatch.setattr(youtube_source.time, "sleep", lambda *_: None)


def test_timeout_is_generous_enough_for_a_long_video():
    """8 seconds cut off real successes; the timeout must clear the slowest
    measured success (30.5s) and the ~40s a 502 takes."""
    assert youtube_source.CAPTION_TIMEOUT_SECONDS >= 45


def test_slow_request_is_given_the_full_timeout(monkeypatch):
    seen = {}

    def fake_get(url, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        return FakeResponse()

    monkeypatch.setattr(youtube_source.requests, "get", fake_get)
    r = youtube_source._request_caption(CAPTION_URL, None, "id")
    assert r is not None
    assert seen["timeout"] == youtube_source.CAPTION_TIMEOUT_SECONDS


def test_timeout_is_not_treated_as_a_block(monkeypatch):
    """A timeout is a slow request, not a refusal: it must not raise
    YouTubeBlocked, because that stops every remaining tier for 600s."""
    def fake_get(url, **kwargs):
        raise requests.Timeout("read timed out")

    monkeypatch.setattr(youtube_source.requests, "get", fake_get)
    assert youtube_source._request_caption(CAPTION_URL, None, "id") is None


def test_502_is_handed_back_not_retried(monkeypatch):
    """A 502 is random, but retrying inside _request_caption would double the
    requests and slip past YTDLP_MAX_CAPTION_REQUESTS (issue #9). One request
    per call; the caller falls through to the next proxy and candidate."""
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse(status_code=502, content_type="text/html")

    monkeypatch.setattr(youtube_source.requests, "get", fake_get)
    r = youtube_source._request_caption(CAPTION_URL, None, "id")
    assert len(calls) == 1
    assert r.status_code == 502


def test_requests_stay_within_the_issue_9_cap(monkeypatch):
    """The caption requests of one call must not exceed candidates x attempts;
    nothing may multiply them behind the cap's back."""
    calls = []

    class FakeYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            return {
                "subtitles": {},
                "automatic_captions": {
                    "id": [{"ext": "json3", "url": CAPTION_URL}],
                    "en": [{"ext": "json3", "url": CAPTION_URL + "&lang=en"}],
                },
            }

    def fake_get(url, **kwargs):
        calls.append(url)
        return FakeResponse(status_code=502, content_type="text/html")

    monkeypatch.setattr(youtube_source.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(youtube_source.requests, "get", fake_get)
    assert youtube_source.fetch_transcript_ytdlp("abcdefghijk") == []
    assert len(calls) <= youtube_source.YTDLP_MAX_CAPTION_REQUESTS


def test_progress_is_reported_for_each_candidate(monkeypatch):
    """A 60s timeout per request can keep this running for minutes; without a
    sign of life the SSE stream goes quiet long enough to be dropped."""
    seen = []

    class FakeYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            return {
                "subtitles": {},
                "automatic_captions": {
                    "id": [{"ext": "json3", "url": CAPTION_URL}],
                    "en": [{"ext": "json3", "url": CAPTION_URL + "&lang=en"}],
                },
            }

    monkeypatch.setattr(youtube_source.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(
        youtube_source.requests, "get",
        lambda url, **kw: FakeResponse(status_code=502, content_type="text/html"),
    )
    youtube_source.fetch_transcript_ytdlp("abcdefghijk", notify=seen.append)
    assert len(seen) >= 2
    assert all("Fetching subtitles" in line for line in seen)


def test_429_still_counts_as_a_block(monkeypatch):
    """Regression guard: a real refusal must still stop the tiers."""
    def fake_get(url, **kwargs):
        return FakeResponse(status_code=429, content_type="text/html")

    monkeypatch.setattr(youtube_source.requests, "get", fake_get)
    # _request_caption hands the 429 back; the caller turns it into a block.
    r = youtube_source._request_caption(CAPTION_URL, None, "id")
    assert r.status_code == 429
    assert youtube_source.youtube_errors.is_blocked_response(429, "text/html", "")


def test_429_from_a_caption_stops_the_tiers(monkeypatch):
    """End to end through fetch_transcript_ytdlp: a 429 raises YouTubeBlocked."""
    class FakeYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            return {
                "subtitles": {},
                "automatic_captions": {
                    "id": [{"ext": "json3", "url": CAPTION_URL}]
                },
            }

    monkeypatch.setattr(youtube_source.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(
        youtube_source.requests, "get",
        lambda url, **kw: FakeResponse(status_code=429, content_type="text/html"),
    )
    with pytest.raises(YouTubeBlocked):
        youtube_source.fetch_transcript_ytdlp("abcdefghijk")


def test_slow_caption_is_returned_instead_of_being_cut_off(monkeypatch):
    """The whole point of the issue: a caption that takes a while still lands."""
    class FakeYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download=False):
            return {
                "subtitles": {},
                "automatic_captions": {
                    "id": [{"ext": "json3", "url": CAPTION_URL}]
                },
            }

    monkeypatch.setattr(youtube_source.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(youtube_source.requests, "get", lambda url, **kw: FakeResponse())
    result = youtube_source.fetch_transcript_ytdlp("abcdefghijk")
    assert [seg["text"] for seg in result] == ["halo", "dunia"]
