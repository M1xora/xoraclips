"""
Tests for issue #12: Gemini failures map to codes the user can act on.
Error texts follow the shapes the google-genai SDK raises.
"""
import pytest

import ai_errors as e


@pytest.mark.parametrize("text, code", [
    ("400 INVALID_ARGUMENT. {'error': {'code': 400, 'message': 'API key not valid. Please pass a valid API key.', "
     "'status': 'INVALID_ARGUMENT', 'details': [{'reason': 'API_KEY_INVALID'}]}}", e.KEY_INVALID),
    ("403 PERMISSION_DENIED. Method doesn't allow unregistered callers.", e.KEY_INVALID),
    ("401 UNAUTHENTICATED. Request had invalid authentication credentials.", e.KEY_INVALID),
    ("400 API key expired. Please renew the API key.", e.KEY_INVALID),
    ("429 RESOURCE_EXHAUSTED. You exceeded your current quota, please check your plan.", e.KEY_QUOTA),
    ("403 Quota exceeded for quota metric 'Generate Content API requests per minute'", e.KEY_QUOTA),
    ("404 NOT_FOUND. models/gemini-9.9-flash is not found for API version v1beta", e.MODEL_UNAVAILABLE),
    ("503 UNAVAILABLE. The model is overloaded. Please try again later.", e.AI_BUSY),
    ("500 INTERNAL. An internal error has occurred.", e.AI_BUSY),
    ("Connection reset by peer", e.AI_FAILED),
])
def test_classify_gemini_error(text, code):
    assert e.classify_gemini_error(RuntimeError(text)) == code


def test_every_code_has_a_message_and_status():
    for code in (e.KEY_MISSING, e.KEY_INVALID, e.KEY_QUOTA, e.MODEL_UNAVAILABLE, e.AI_BUSY, e.AI_FAILED):
        event = e.error_event(code)
        assert event["code"] == code and event["error"] and event["status"] >= 400


def test_busy_message_tells_the_user_their_key_is_fine():
    assert "key is fine" in e.MESSAGES[e.AI_BUSY]


def test_key_problems_point_to_ai_studio_or_changing_the_key():
    assert "AI Studio" in e.MESSAGES[e.KEY_MISSING]
    assert "AI Studio" in e.MESSAGES[e.KEY_INVALID]
    assert "different key" in e.MESSAGES[e.KEY_QUOTA]


# --- Review findings ---------------------------------------------------------

@pytest.mark.parametrize("text, code", [
    ("400 FAILED_PRECONDITION. User location is not supported for the API use.", e.REGION_UNSUPPORTED),
    # Digits inside the text are not a status code.
    ("Response parse error at offset 1403 of 4011 bytes", e.AI_FAILED),
    ("Request id 40312345 timed out", e.AI_FAILED),
    ("400 INVALID_ARGUMENT. Request payload size exceeds the limit.", e.AI_FAILED),
])
def test_only_the_leading_status_counts(text, code):
    assert e.classify_gemini_error(RuntimeError(text)) == code


def test_a_plain_403_does_not_stop_the_other_models():
    preview_denied = RuntimeError("403 PERMISSION_DENIED. You do not have access to gemini-3.0-flash-preview.")
    bad_key = RuntimeError("400 INVALID_ARGUMENT. API key not valid. [API_KEY_INVALID]")
    assert e.classify_gemini_error(preview_denied) == e.KEY_INVALID
    assert e.is_definitely_bad_key(preview_denied) is False
    assert e.is_definitely_bad_key(bad_key) is True
    assert e.is_definitely_bad_key(RuntimeError("401 UNAUTHENTICATED")) is True


@pytest.mark.parametrize("codes, expected", [
    # Busy flash models, then a retired model returning 404: report "busy".
    ([e.AI_BUSY, e.AI_BUSY, e.MODEL_UNAVAILABLE], e.AI_BUSY),
    ([e.MODEL_UNAVAILABLE, e.KEY_QUOTA], e.KEY_QUOTA),
    ([e.AI_FAILED, e.KEY_INVALID, e.AI_BUSY], e.KEY_INVALID),
    ([e.MODEL_UNAVAILABLE, e.MODEL_UNAVAILABLE], e.MODEL_UNAVAILABLE),
    ([], e.AI_FAILED),
])
def test_most_relevant_error_wins(codes, expected):
    assert e.most_relevant(codes) == expected


# ── Issue #124: the server's own retry hint ──────────────────────────────


class _Err(Exception):
    """Stands in for google-genai's APIError, which carries the response JSON."""

    def __init__(self, details):
        super().__init__("429 RESOURCE_EXHAUSTED")
        self.details = details


def _retry_info(delay):
    return {"error": {"code": 429, "details": [
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay},
    ]}}


@pytest.mark.parametrize("text,seconds", [
    ("53s", 53.0),
    ("46.13s", 46.13),
    ("1m30s", 90.0),
    # A daily quota: reported as hours, and far past any sensible wait.
    ("10h17m5.72s", 37025.72),
    ("", None),
    ("soon", None),
    (None, None),
    (5, None),
])
def test_parse_retry_duration(text, seconds):
    got = e.parse_retry_duration(text)
    if seconds is None:
        assert got is None
    else:
        assert got == pytest.approx(seconds)


def test_retry_after_seconds_reads_the_servers_hint():
    assert e.retry_after_seconds(_Err(_retry_info("53s"))) == pytest.approx(53.0)
    # Works without the "error" wrapper too, as some responses come.
    bare = {"details": [{"@type": "google.rpc.RetryInfo", "retryDelay": "7s"}]}
    assert e.retry_after_seconds(_Err(bare)) == pytest.approx(7.0)


def test_a_daily_quota_is_reported_as_its_real_length():
    """It must not be mistaken for a per-minute limit: the caller compares it
    against its own ceiling and falls through to the next model."""
    assert e.retry_after_seconds(_Err(_retry_info("10h17m5.72s"))) > 3600


@pytest.mark.parametrize("details", [
    {"error": {"code": 429}},                                   # no details
    {"error": {"details": [{"@type": "google.rpc.QuotaFailure"}]}},  # other type
    {"error": {"details": [{"@type": "google.rpc.RetryInfo"}]}},     # no delay
    {"error": {"details": "not a list"}},
    "not a dict",
    None,
])
def test_no_hint_means_none_so_the_caller_keeps_its_old_behaviour(details):
    assert e.retry_after_seconds(_Err(details)) is None


def test_a_plain_exception_has_no_hint():
    assert e.retry_after_seconds(Exception("boom")) is None
