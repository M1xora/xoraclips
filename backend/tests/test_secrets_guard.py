"""
Tests for issue #8: the Gemini key never reaches a log line.
"""
import io
import logging

import pytest

from secrets_guard import (
    REDACTED,
    RedactingFilter,
    get_gemini_key,
    install_log_redaction,
    is_mock_mode,
    redact,
)

# Fake keys in the two Google shapes. Never real.
SERVER_KEY = "AIzaSyFAKE_SERVER_KEY_0123456789abcdef"
OTHER_KEY = "AQ.FAKEother_key_0123456789ABCDEFGHIJ"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", SERVER_KEY)
    monkeypatch.delenv("MOCK_MODE", raising=False)


def test_key_comes_only_from_env(monkeypatch):
    assert get_gemini_key() == SERVER_KEY
    monkeypatch.setenv("GEMINI_API_KEY", "  spaced  ")
    assert get_gemini_key() == "spaced"
    monkeypatch.delenv("GEMINI_API_KEY")
    assert get_gemini_key() == ""


@pytest.mark.parametrize("value, expected", [
    ("true", True), ("1", True), ("YES", True), ("on", True),
    ("false", False), ("0", False), ("", False), ("mock", False),
])
def test_mock_mode_setting(monkeypatch, value, expected):
    monkeypatch.setenv("MOCK_MODE", value)
    assert is_mock_mode() is expected


@pytest.mark.parametrize("text", [
    f"key is {SERVER_KEY}",
    f"GET /api/models?api_key={SERVER_KEY}",
    f"GET /api/models?api_key=plain-text-secret",
    f"https://generativelanguage.googleapis.com/v1beta/models?key={OTHER_KEY}&pageSize=5",
    f"https://example.com/x?foo=1&key=abcdef123456",
    f"headers={{'x-goog-api-key': '{OTHER_KEY}'}}",
    f"403 PERMISSION_DENIED: API key {OTHER_KEY} not valid",
])
def test_redact_removes_every_key_shape(text):
    cleaned = redact(text)
    assert REDACTED in cleaned
    for secret in (SERVER_KEY, OTHER_KEY, "plain-text-secret", "abcdef123456"):
        assert secret not in cleaned


def test_redact_leaves_ordinary_text_alone():
    text = "GET /api/health?refresh=true HTTP/1.1 200 (monkey keyboard)"
    assert redact(text) == text


def _capture(logger_name, formatter=None):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    if formatter:
        handler.setFormatter(formatter)
    handler.addFilter(RedactingFilter())
    lg = logging.getLogger(logger_name)
    lg.addHandler(handler)
    lg.setLevel(logging.DEBUG)
    return lg, handler, stream


def test_uvicorn_access_log_line_is_scrubbed():
    """The exact leak from issue #8: the access log printed the query string."""
    from uvicorn.logging import AccessFormatter

    lg, handler, stream = _capture(
        "test.uvicorn.access",
        AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False),
    )
    try:
        lg.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET",
                f"/api/models?api_key={SERVER_KEY}", "1.1", 200)
    finally:
        lg.removeHandler(handler)
    out = stream.getvalue()
    assert "GET /api/models?api_key=[REDACTED]" in out
    assert SERVER_KEY not in out


def test_arguments_and_exceptions_are_scrubbed():
    lg, handler, stream = _capture("test.app")
    try:
        lg.warning("Gemini said: %s", Exception(f"invalid key {SERVER_KEY}"))
        try:
            raise RuntimeError(f"boom with {OTHER_KEY}")
        except RuntimeError:
            lg.exception("failed")
    finally:
        lg.removeHandler(handler)
    out = stream.getvalue()
    assert SERVER_KEY not in out and OTHER_KEY not in out
    assert out.count(REDACTED) == 2


def test_app_loggers_are_scrubbed_at_the_source():
    """A handler added after installation (a log file, say) still sees no key."""
    install_log_redaction()
    stream = io.StringIO()
    late_handler = logging.StreamHandler(stream)  # deliberately without the filter
    app_logger = logging.getLogger("cheat-clip-pro")
    app_logger.addHandler(late_handler)
    try:
        app_logger.error(f"calling Gemini with {SERVER_KEY}")
    finally:
        app_logger.removeHandler(late_handler)
    assert SERVER_KEY not in stream.getvalue()
    assert REDACTED in stream.getvalue()


# --- Review findings ---------------------------------------------------------

def test_payload_redaction_keeps_json_valid():
    """Redacting serialized JSON could cut an escaped quote; redact the values first."""
    import json
    from secrets_guard import redact_data

    payload = {"error": f'403 for "https://www.youtube.com/youtubei/v1/player?key={SERVER_KEY}" blocked',
               "nested": [{"t": f"key={OTHER_KEY}"}], "n": 3}
    text = json.dumps(redact_data(payload), ensure_ascii=False)
    parsed = json.loads(text)
    assert SERVER_KEY not in text and OTHER_KEY not in text
    assert parsed["n"] == 3 and parsed["error"].endswith('" blocked')


def test_placeholders_and_arguments_stay_in_step(capsys):
    """A template containing '?key=%s' must not lose its placeholder."""
    install_log_redaction()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    lg = logging.getLogger("test.placeholders")
    lg.addHandler(handler)
    try:
        lg.warning("calling %s?key=%s", "https://example.com/v1", "plain-secret-value")
    finally:
        lg.removeHandler(handler)
    assert "Logging error" not in capsys.readouterr().err
    out = stream.getvalue()
    assert "https://example.com/v1?key=[REDACTED]" in out
    assert "plain-secret-value" not in out


def test_message_that_is_an_exception_object_is_scrubbed():
    install_log_redaction()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    lg = logging.getLogger("test.objmsg")
    lg.addHandler(handler)
    try:
        lg.error(RuntimeError(f"403 PERMISSION_DENIED: API key {SERVER_KEY} not valid"))
    finally:
        lg.removeHandler(handler)
    assert SERVER_KEY not in stream.getvalue()
    assert REDACTED in stream.getvalue()


def test_library_child_logger_with_a_late_handler_is_scrubbed():
    """Records from e.g. google_genai._api_client reach handlers added after install."""
    install_log_redaction()
    stream = io.StringIO()
    late = logging.StreamHandler(stream)  # no filter attached
    root = logging.getLogger()
    root.addHandler(late)
    old_level = root.level
    root.setLevel(logging.DEBUG)
    try:
        logging.getLogger("google_genai._api_client").warning(f"request failed for key {OTHER_KEY}")
        logging.getLogger("httpx").info(f"HTTP Request: GET https://x.googleapis.com/v1?key={SERVER_KEY}")
    finally:
        root.removeHandler(late)
        root.setLevel(old_level)
    out = stream.getvalue()
    assert SERVER_KEY not in out and OTHER_KEY not in out
    assert out.count(REDACTED) == 2


def test_install_is_idempotent():
    install_log_redaction()
    factory = logging.getLogRecordFactory()
    install_log_redaction()
    assert logging.getLogRecordFactory() is factory
