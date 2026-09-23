"""
What went wrong with a Gemini call, as a short code the frontend can turn
into a clear, translated message (issue #12).

The key belongs to the user, so the user must be able to tell "my key is
wrong / out of quota, I should change it" apart from "Google is busy, my key
is fine".
"""
from typing import Dict

KEY_MISSING = "key_missing"
KEY_INVALID = "key_invalid"
KEY_QUOTA = "key_quota"
MODEL_UNAVAILABLE = "model_unavailable"
AI_BUSY = "ai_busy"
AI_FAILED = "ai_failed"

# English fallbacks; the frontend shows its own translated text per code.
MESSAGES: Dict[str, str] = {
    KEY_MISSING: "Enter your Gemini API key to run the analysis. You can create one for free in Google AI Studio.",
    KEY_INVALID: "Google rejected your Gemini API key. Check that it was copied completely, or create a new key in Google AI Studio.",
    KEY_QUOTA: "Your Gemini API key has run out of quota. Wait a minute and try again, or use a different key.",
    MODEL_UNAVAILABLE: "The selected model is not available for your key. Choose another model and try again.",
    AI_BUSY: "Google's AI service is busy right now. Your key is fine; please try again in a few moments.",
    AI_FAILED: "The AI analysis failed. Please try again in a few moments.",
}

STATUS: Dict[str, int] = {
    KEY_MISSING: 401,
    KEY_INVALID: 401,
    KEY_QUOTA: 429,
    MODEL_UNAVAILABLE: 404,
    AI_BUSY: 503,
    AI_FAILED: 500,
}

_INVALID = (
    "api_key_invalid", "api key not valid", "invalid api key", "api key expired",
    "permission_denied", "unauthenticated", "401", "403",
)
_QUOTA = ("resource_exhausted", "resource exhausted", "quota", "rate limit", "429")
_MODEL = ("404", "not found", "not supported")
_BUSY = ("503", "unavailable", "overloaded", "500", "internal")


def classify_gemini_error(error: object) -> str:
    """Maps an exception (or its text) from the Gemini SDK to an error code."""
    text = str(error).lower()
    # Quota before "invalid": Google reports some quota errors with 403 too.
    if any(x in text for x in _QUOTA):
        return KEY_QUOTA
    if any(x in text for x in _INVALID):
        return KEY_INVALID
    if any(x in text for x in _MODEL):
        return MODEL_UNAVAILABLE
    if any(x in text for x in _BUSY):
        return AI_BUSY
    return AI_FAILED


def error_event(code: str) -> dict:
    """The SSE error payload for a code."""
    return {"error": MESSAGES[code], "code": code, "status": STATUS[code]}
