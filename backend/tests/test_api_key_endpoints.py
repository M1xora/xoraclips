"""
Tests for issue #12 against the real FastAPI app: the user's key arrives
only in the X-Gemini-Api-Key header. Gemini and YouTube are fakes: nothing
here touches the network.
"""
import json
import logging

import pytest
from fastapi.testclient import TestClient

import main

USER_KEY = "AIzaSyFAKE_USER_KEY_0123456789abcdefgh"
ODD_KEY = "user-pasted-key-without-google-shape-777"
URL_KEY = "AIzaSyURL_KEY_SHOULD_BE_IGNORED_zzzzzzz"
HEADER = "X-Gemini-Api-Key"


class FakeGemini:
    """Stands in for google.genai.Client; records keys and fails as configured."""

    created_with = []
    failure = "403 PERMISSION_DENIED: API key {key} not valid. key={key}"

    def __init__(self, api_key=None, **kwargs):
        FakeGemini.created_with.append(api_key)
        self.api_key = api_key
        self.models = self

    def _fail(self):
        raise RuntimeError(FakeGemini.failure.format(key=self.api_key))

    def list(self, *args, **kwargs):
        self._fail()

    def generate_content(self, *args, **kwargs):
        self._fail()


def no_youtube(*args, **kwargs):
    raise AssertionError("YouTube must not be contacted in this test")


class InstantAsyncio:
    """main.py's asyncio, with retry back-off and progress pauses made instant."""

    def __getattr__(self, name):
        return getattr(main_asyncio, name)

    @staticmethod
    async def sleep(*args, **kwargs):
        return None


main_asyncio = main.asyncio


@pytest.fixture
def client(monkeypatch):
    FakeGemini.created_with = []
    FakeGemini.failure = "403 PERMISSION_DENIED: API key {key} not valid. key={key}"
    monkeypatch.setattr(main.genai, "Client", FakeGemini)
    monkeypatch.setattr(main, "fetch_video_metadata", no_youtube)
    monkeypatch.setattr(main, "fetch_transcript", no_youtube)
    monkeypatch.setattr(main.time, "sleep", lambda *_: None)
    monkeypatch.setattr(main, "asyncio", InstantAsyncio())
    monkeypatch.delenv("MOCK_MODE", raising=False)
    # A key in .env must be ignored completely.
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyENV_KEY_MUST_NEVER_BE_USED_xxxxx")
    return TestClient(main.app)


@pytest.fixture
def youtube_ok(monkeypatch):
    monkeypatch.setattr(main, "fetch_video_metadata", lambda *a, **k: {
        "title": "Uji", "channel": "Kanal", "duration": 120.0, "heatmap": [],
        "is_live": False, "live_status": "not_live",
    })
    monkeypatch.setattr(main, "fetch_transcript", lambda *a, **k: [
        {"text": f"kalimat nomor {i}", "start": i * 5.0, "duration": 5.0} for i in range(20)
    ])


def events(response):
    return [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith("data:")]


def errors(response):
    return [e for e in events(response) if "error" in e]


def analyze(client, key=None, **extra):
    body = {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", **extra}
    headers = {HEADER: key} if key is not None else {}
    return client.post("/api/analyze", json=body, headers=headers)


# --- where the key comes from -------------------------------------------------

def test_analyze_uses_the_header_key(client, youtube_ok):
    analyze(client, key=USER_KEY)
    assert FakeGemini.created_with and set(FakeGemini.created_with) == {USER_KEY}


def test_no_key_means_key_missing_even_with_a_key_in_env_or_body(client):
    res = analyze(client, api_key=URL_KEY)
    assert [(e["code"], e["status"]) for e in errors(res)] == [("key_missing", 401)]
    assert "AI Studio" in errors(res)[0]["error"]
    assert FakeGemini.created_with == []


def test_blank_header_counts_as_missing(client):
    assert errors(analyze(client, key="   "))[0]["code"] == "key_missing"


def test_model_list_uses_the_header_key_and_ignores_the_url(client):
    FakeGemini.failure = "503 UNAVAILABLE"
    res = client.get(f"/api/models?api_key={URL_KEY}", headers={HEADER: USER_KEY})
    assert res.status_code == 200
    assert FakeGemini.created_with == [USER_KEY]


def test_model_list_without_key_returns_defaults_and_calls_nobody(client):
    res = client.get(f"/api/models?api_key={URL_KEY}")
    assert res.status_code == 200 and res.json()["models"]
    assert FakeGemini.created_with == []


def test_mock_mode_needs_no_key_and_contacts_nobody(client, monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "true")
    evs = events(analyze(client))
    assert not [e for e in evs if "error" in e]
    final = [e for e in evs if "result" in e]
    assert final and final[-1]["result"]["clips"]
    assert FakeGemini.created_with == []


def test_health_has_no_server_key_field(client, monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "1")
    body = client.get("/api/health").json()
    assert body["mock_mode"] is True
    assert "gemini_env_configured" not in body


# --- clear errors when the key is the problem ---------------------------------

@pytest.mark.parametrize("failure, code", [
    ("400 INVALID_ARGUMENT. API key not valid. Please pass a valid API key. [API_KEY_INVALID] {key}", "key_invalid"),
    ("429 RESOURCE_EXHAUSTED. You exceeded your current quota.", "key_quota"),
    ("503 UNAVAILABLE. The model is overloaded.", "ai_busy"),
])
def test_analysis_errors_carry_a_code(client, youtube_ok, failure, code):
    FakeGemini.failure = failure
    errs = errors(analyze(client, key=USER_KEY))
    assert errs and errs[-1]["code"] == code


def test_rejected_key_stops_after_the_first_model(client, youtube_ok):
    FakeGemini.failure = "400 API key not valid. [API_KEY_INVALID]"
    analyze(client, key=USER_KEY)
    # One client per model tried; a rejected key must not be retried on every model.
    assert len(FakeGemini.created_with) <= 2


@pytest.mark.parametrize("failure, status, code", [
    ("400 API key not valid. [API_KEY_INVALID]", 401, "key_invalid"),
    ("429 RESOURCE_EXHAUSTED quota", 429, "key_quota"),
])
def test_model_list_reports_a_bad_key(client, failure, status, code):
    FakeGemini.failure = failure
    res = client.get("/api/models", headers={HEADER: USER_KEY})
    assert res.status_code == status
    assert res.json()["detail"]["code"] == code


# --- the key never leaks --------------------------------------------------------

@pytest.mark.parametrize("key", [USER_KEY, ODD_KEY])
def test_key_never_reaches_logs_or_the_user(client, youtube_ok, caplog, key):
    """Gemini fails with an error quoting the key, in Google shape or not."""
    main.install_log_redaction()
    with caplog.at_level(logging.DEBUG):
        res = analyze(client, key=key)
        models = client.get("/api/models", headers={HEADER: key})
    assert FakeGemini.created_with and set(FakeGemini.created_with) == {key}
    assert errors(res)
    for text in (res.text, models.text, caplog.text):
        assert key not in text


def test_scrubbed_errors_are_still_valid_json(client, monkeypatch):
    def blocked(*args, **kwargs):
        raise RuntimeError(f'403 for "https://www.youtube.com/youtubei/v1/player?key={USER_KEY}" blocked')
    monkeypatch.setattr(main, "fetch_video_metadata", blocked)
    res = analyze(client, key=USER_KEY)
    errs = errors(res)  # json.loads on every frame: raises if any frame is invalid
    assert errs and errs[-1]["error"].endswith('" blocked')
    assert USER_KEY not in res.text
