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
