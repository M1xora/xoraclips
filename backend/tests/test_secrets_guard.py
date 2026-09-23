"""
Tests for issues #8/#12: a Gemini key never reaches a log line.
"""
import io
import json
import logging

import pytest

from secrets_guard import (
    REDACTED,
    RedactingFilter,
    install_log_redaction,
    is_mock_mode,
    redact,
    redact_data,
    tracked_secret,
    user_key_from_header,
)

# Fake keys. Never real.
USER_KEY = "AIzaSyFAKE_USER_KEY_0123456789abcdefgh"
OTHER_KEY = "AQ.FAKEother_key_0123456789ABCDEFGHIJ"
ODD_KEY = "not-a-google-shape-but-still-secret-42"  # only caught while tracked


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.delenv("MOCK_MODE", raising=False)


def test_user_key_from_header():
    assert user_key_from_header(f"  {USER_KEY} ") == USER_KEY
    assert user_key_from_header("   ") is None
    assert user_key_from_header(None) is None


@pytest.mark.parametrize("value, expected", [
    ("true", True), ("1", True), ("YES", True), ("on", True),
    ("false", False), ("0", False), ("", False), ("mock", False),
])
def test_mock_mode_setting(monkeypatch, value, expected):
    monkeypatch.setenv("MOCK_MODE", value)
    assert is_mock_mode() is expected


@pytest.mark.parametrize("text", [
    f"key is {USER_KEY}",
    f"GET /api/models?api_key={USER_KEY}",
    "GET /api/models?api_key=plain-text-secret",
    f"https://generativelanguage.googleapis.com/v1beta/models?key={OTHER_KEY}&pageSize=5",
    "https://example.com/x?foo=1&key=abcdef123456",
    f"headers={{'x-goog-api-key': '{OTHER_KEY}'}}",
    f"headers={{'X-Gemini-Api-Key': 'whatever-value-here'}}",
    f"403 PERMISSION_DENIED: API key {OTHER_KEY} not valid",
])
def test_redact_removes_every_key_shape(text):
    cleaned = redact(text)
    assert REDACTED in cleaned
    for secret in (USER_KEY, OTHER_KEY, "plain-text-secret", "abcdef123456", "whatever-value-here"):
        assert secret not in cleaned


def test_tracked_key_of_any_shape_is_scrubbed_only_while_in_use():
    assert redact(f"x {ODD_KEY} y") == f"x {ODD_KEY} y"  # not a Google shape
    with tracked_secret(ODD_KEY):
        assert redact(f"x {ODD_KEY} y") == f"x {REDACTED} y"
    assert redact(f"x {ODD_KEY} y") == f"x {ODD_KEY} y"  # nothing kept after the request


def test_overlapping_requests_with_the_same_key():
    with tracked_secret(ODD_KEY):
        with tracked_secret(ODD_KEY):
            pass
        assert ODD_KEY not in redact(ODD_KEY)  # still in use by the outer request


def test_short_values_are_not_tracked():
    with tracked_secret("abc"):
        assert redact("abcabc") == "abcabc"


def test_redact_leaves_ordinary_text_alone():
    text = "GET /api/health?refresh=true HTTP/1.1 200 (monkey keyboard)"
    assert redact(text) == text


def test_payload_redaction_keeps_json_valid():
    payload = {"error": f'403 for "https://www.youtube.com/youtubei/v1/player?key={USER_KEY}" blocked',
               "nested": [{"t": f"key={OTHER_KEY}"}], "n": 3}
    text = json.dumps(redact_data(payload), ensure_ascii=False)
    parsed = json.loads(text)
    assert USER_KEY not in text and OTHER_KEY not in text
    assert parsed["n"] == 3 and parsed["error"].endswith('" blocked')


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
    """The original leak from issue #8: the access log printed the query string."""
    from uvicorn.logging import AccessFormatter

    lg, handler, stream = _capture(
        "test.uvicorn.access",
        AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False),
    )
    try:
        lg.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET",
                f"/api/models?api_key={USER_KEY}", "1.1", 200)
    finally:
        lg.removeHandler(handler)
    out = stream.getvalue()
    assert "GET /api/models?api_key=[REDACTED]" in out
    assert USER_KEY not in out


def test_arguments_and_exceptions_are_scrubbed():
    lg, handler, stream = _capture("test.app")
    try:
        lg.warning("Gemini said: %s", Exception(f"invalid key {USER_KEY}"))
        try:
            raise RuntimeError(f"boom with {OTHER_KEY}")
        except RuntimeError:
            lg.exception("failed")
    finally:
        lg.removeHandler(handler)
    out = stream.getvalue()
    assert USER_KEY not in out and OTHER_KEY not in out
    assert out.count(REDACTED) == 2


def test_placeholders_and_arguments_stay_in_step(capsys):
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
        lg.error(RuntimeError(f"403 PERMISSION_DENIED: API key {USER_KEY} not valid"))
    finally:
        lg.removeHandler(handler)
    assert USER_KEY not in stream.getvalue()
    assert REDACTED in stream.getvalue()


def test_any_logger_and_late_handler_is_scrubbed_including_tracked_keys():
    install_log_redaction()
    stream = io.StringIO()
    late = logging.StreamHandler(stream)  # no filter attached
    root = logging.getLogger()
    root.addHandler(late)
    old_level = root.level
    root.setLevel(logging.DEBUG)
    try:
        with tracked_secret(ODD_KEY):
            logging.getLogger("google_genai._api_client").warning(f"request failed for key {ODD_KEY}")
            logging.getLogger("cheat-clip-pro").error(f"calling Gemini with {USER_KEY}")
    finally:
        root.removeHandler(late)
        root.setLevel(old_level)
    out = stream.getvalue()
    assert ODD_KEY not in out and USER_KEY not in out
    assert out.count(REDACTED) == 2


def test_install_is_idempotent():
    install_log_redaction()
    factory = logging.getLogRecordFactory()
    install_log_redaction()
    assert logging.getLogRecordFactory() is factory
