"""
Tests for issue #8 against the real FastAPI app. Gemini and YouTube are
replaced with fakes: nothing here touches the network.
"""
import json
import logging

import pytest
from fastapi.testclient import TestClient

import main

SERVER_KEY = "AIzaSyFAKE_SERVER_KEY_0123456789abcdef"
ATTACKER_KEY = "AIzaSyATTACKER_KEY_zzzzzzzzzzzzzzzzzzzz"


class FakeGemini:
    """Stands in for google.genai.Client and records the key it was given."""

    created_with = []

    def __init__(self, api_key=None, **kwargs):
        FakeGemini.created_with.append(api_key)
        self.models = self

    def list(self, *args, **kwargs):
        raise RuntimeError(f"403 PERMISSION_DENIED: API key {self_key()} not valid")

    def generate_content(self, *args, **kwargs):
        raise RuntimeError(f"403 PERMISSION_DENIED: API key {self_key()} not valid. key={self_key()}")


def self_key():
    return FakeGemini.created_with[-1] if FakeGemini.created_with else ""


def no_youtube(*args, **kwargs):
    raise AssertionError("YouTube must not be contacted in this test")


@pytest.fixture
def client(monkeypatch):
    FakeGemini.created_with = []
    monkeypatch.setattr(main.genai, "Client", FakeGemini)
    monkeypatch.setattr(main, "fetch_video_metadata", no_youtube)
    monkeypatch.setattr(main, "fetch_transcript", no_youtube)
    monkeypatch.setenv("GEMINI_API_KEY", SERVER_KEY)
    monkeypatch.delenv("MOCK_MODE", raising=False)
    return TestClient(main.app)


def events(response):
    return [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:")]


def analyze(client, **extra):
    body = {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", **extra}
    return client.post("/api/analyze", json=body)


def test_model_list_ignores_a_key_in_the_url(client):
    res = client.get(f"/api/models?api_key={ATTACKER_KEY}")
    assert res.status_code == 200
    assert FakeGemini.created_with == [SERVER_KEY]


def test_analyze_ignores_a_key_in_the_body(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    res = analyze(client, api_key=ATTACKER_KEY)
    errors = [e["error"] for e in events(res) if "error" in e]
    assert errors == ["The AI service is not configured on the server yet. Please contact the administrator."]
    assert FakeGemini.created_with == []


def test_mock_mode_works_without_key_gemini_or_youtube(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.setenv("MOCK_MODE", "true")
    evs = events(analyze(client))
    assert not [e for e in evs if "error" in e]
    final = [e for e in evs if "result" in e]
    assert final and final[-1]["result"]["clips"]
    assert FakeGemini.created_with == []


def test_mock_mode_is_not_triggered_by_typing_mock(client, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    errors = [e for e in events(analyze(client, api_key="mock")) if "error" in e]
    assert errors  # "mock" as a key means nothing any more


def test_health_reports_configuration(client, monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "1")
    body = client.get("/api/health").json()
    assert body["gemini_env_configured"] is True
    assert body["mock_mode"] is True
    assert SERVER_KEY not in json.dumps(body)


def test_key_never_reaches_logs_or_the_user(client, monkeypatch, caplog):
    """Gemini fails with an error that quotes the key; nothing may leak it."""
    monkeypatch.setattr(main, "fetch_video_metadata", lambda *a, **k: {
        "title": "Uji", "channel": "Kanal", "duration": 120.0, "heatmap": [],
        "is_live": False, "live_status": "not_live",
    })
    monkeypatch.setattr(main, "fetch_transcript", lambda *a, **k: [
        {"text": f"kalimat nomor {i}", "start": i * 5.0, "duration": 5.0} for i in range(20)
    ])
    monkeypatch.setattr(main.time, "sleep", lambda *_: None)
    main.install_log_redaction()

    with caplog.at_level(logging.DEBUG):
        res = analyze(client)
        client.get(f"/api/models?api_key={SERVER_KEY}")

    assert FakeGemini.created_with and set(FakeGemini.created_with) == {SERVER_KEY}
    assert any("error" in e for e in events(res))
    assert SERVER_KEY not in res.text
    assert SERVER_KEY not in caplog.text
    assert "aistudio" not in res.text and "change your" not in res.text.lower()


# --- Review findings ---------------------------------------------------------

def test_scrubbed_errors_are_still_valid_json(client, monkeypatch):
    """A YouTube error quoting '...?key=..." blocked' must not break the SSE frame."""
    def blocked(*args, **kwargs):
        raise RuntimeError(f'403 for "https://www.youtube.com/youtubei/v1/player?key={SERVER_KEY}" blocked')
    monkeypatch.setattr(main, "fetch_video_metadata", blocked)

    res = analyze(client)
    evs = events(res)  # json.loads on every frame: raises if any frame is invalid
    errors = [e["error"] for e in evs if "error" in e]
    assert errors and errors[-1].endswith('" blocked')
    assert SERVER_KEY not in res.text


def test_whitespace_key_counts_as_not_configured(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "   ")
    assert client.get("/api/health").json()["gemini_env_configured"] is False
    errors = [e["error"] for e in events(analyze(client)) if "error" in e]
    assert errors == ["The AI service is not configured on the server yet. Please contact the administrator."]
