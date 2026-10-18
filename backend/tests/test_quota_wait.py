"""
Issue #124: a per-minute limit is waited out so the better model keeps the
job; a daily quota is not, because it does not heal in time.

Nothing here sleeps for real: asyncio.sleep is replaced by a recorder, so the
tests assert on what would have been waited.
"""
import asyncio

import pytest

import ai_errors
import routes_analyze


def quota_error(delay=None):
    """A 429 shaped like google-genai's APIError, with or without RetryInfo."""
    err = Exception("429 RESOURCE_EXHAUSTED. Quota exceeded.")
    if delay is None:
        err.details = {"error": {"code": 429}}
    else:
        err.details = {"error": {"code": 429, "details": [
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay},
        ]}}
    return err


class FakeClient:
    """Answers generate_content() from a scripted list, recording each model."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.models = self

    def generate_content(self, *, model, contents, config):
        self.calls.append(model)
        answer = self.script.pop(0) if self.script else self.script
        if isinstance(answer, Exception):
            raise answer
        return answer


def drive(client, models, monkeypatch):
    """Runs _gemini_events to completion; returns (slept_seconds, stages)."""
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(routes_analyze.asyncio, "sleep", fake_sleep)

    outcome = {}
    stages = []

    async def go():
        async for event in routes_analyze._gemini_events(
            client, models, "prompt", 10, "3-5", outcome
        ):
            stages.append(event)

    asyncio.run(go())
    return slept, stages, outcome


# One usable clip: an empty list counts as a failure and moves the chain on,
# which would hide what these tests are about.
_CLIP = ('{"clips": [{"title": "Judul", "start_time": 1.0, "end_time": 20.0, '
         '"hook_time": 2.0, "virality_score": 80, "key_quotes": ["q"], '
         '"title_options": [{"text": "Judul", "angle": "question"}]}]}')
ANSWER = type("Answer", (), {"text": _CLIP, "parsed": None})()


def test_a_per_minute_limit_is_waited_out_on_the_same_model(monkeypatch):
    """The whole point: the better model keeps the job instead of the chain
    dropping to the weakest model that happens to accept."""
    client = FakeClient([quota_error("53s"), ANSWER])
    slept, _, _ = drive(client, ["gemini-3.8-flash", "gemini-3.5-flash-lite"], monkeypatch)

    assert client.calls == ["gemini-3.8-flash", "gemini-3.8-flash"]
    assert 53.0 in slept


def test_a_daily_quota_drops_to_the_next_model_without_waiting(monkeypatch):
    """Hours of waiting would be worse than a weaker answer."""
    client = FakeClient([quota_error("10h17m5.72s"), ANSWER])
    slept, _, _ = drive(client, ["gemini-3.8-flash", "gemini-3.5-flash-lite"], monkeypatch)

    assert client.calls == ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
    assert not any(s > routes_analyze.QUOTA_WAIT_MAX_SECONDS for s in slept)


def test_no_retry_hint_keeps_the_old_behaviour(monkeypatch):
    """Regression: without RetryInfo the chain moves on exactly as before."""
    client = FakeClient([quota_error(None), ANSWER])
    _, _, _ = drive(client, ["gemini-3.8-flash", "gemini-3.5-flash-lite"], monkeypatch)

    assert client.calls == ["gemini-3.8-flash", "gemini-3.5-flash-lite"]


def test_one_model_is_waited_for_only_once(monkeypatch):
    """A model that keeps answering 429 must not hold the chain for ever."""
    client = FakeClient([quota_error("50s"), quota_error("50s"), ANSWER])
    _, _, _ = drive(client, ["gemini-3.8-flash", "gemini-3.5-flash-lite"], monkeypatch)

    assert client.calls.count("gemini-3.8-flash") == 2
    assert client.calls[-1] == "gemini-3.5-flash-lite"


def test_the_wait_is_announced_so_the_stream_is_not_silent(monkeypatch):
    """A quiet minute looks like a hang to the user and to intermediaries."""
    client = FakeClient([quota_error("53s"), ANSWER])
    _, stages, _ = drive(client, ["gemini-3.8-flash", "gemini-3.5-flash-lite"], monkeypatch)

    assert any("Quota Wait" in str(s) for s in stages)


def test_the_ceiling_is_above_a_minute_and_well_below_a_day():
    assert 60 < routes_analyze.QUOTA_WAIT_MAX_SECONDS < 600
