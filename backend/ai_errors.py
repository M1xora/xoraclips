"""
What went wrong with a Gemini call, as a short code the frontend can turn
into a clear, translated message (issue #12).

The key belongs to the user, so the user must be able to tell "my key is
wrong / out of quota, I should change it" apart from "Google is busy, my key
is fine".
"""
import re
from typing import Dict, Iterable, Optional

KEY_MISSING = "key_missing"
KEY_INVALID = "key_invalid"
KEY_QUOTA = "key_quota"
REGION_UNSUPPORTED = "region_unsupported"
MODEL_UNAVAILABLE = "model_unavailable"
AI_BUSY = "ai_busy"
AI_FAILED = "ai_failed"

# English fallbacks; the frontend shows its own translated text per code.
MESSAGES: Dict[str, str] = {
    KEY_MISSING: "Enter your Gemini API key to run the analysis. You can create one for free in Google AI Studio.",
    KEY_INVALID: "Google rejected your Gemini API key. Check that it was copied completely, or create a new key in Google AI Studio.",
    KEY_QUOTA: "Your Gemini API key has run out of quota. Wait a minute and try again, or use a different key.",
    REGION_UNSUPPORTED: "The Gemini API is not available in your region, so this key cannot be used from here.",
    MODEL_UNAVAILABLE: "The selected model is not available for your key. Choose another model and try again.",
    AI_BUSY: "Google's AI service is busy right now. Your key is fine; please try again in a few moments.",
    AI_FAILED: "The AI analysis failed. Please try again in a few moments.",
}

STATUS: Dict[str, int] = {
    KEY_MISSING: 401,
    KEY_INVALID: 401,
    KEY_QUOTA: 429,
    REGION_UNSUPPORTED: 403,
    MODEL_UNAVAILABLE: 404,
    AI_BUSY: 503,
    AI_FAILED: 500,
}

# When several models failed differently, the most useful one to tell the
# user. A retired model at the end of the fallback chain (404) must not hide
# "Google is busy" or "your key is wrong".
REPORT_PRIORITY = (KEY_INVALID, KEY_QUOTA, REGION_UNSUPPORTED, AI_BUSY, AI_FAILED, MODEL_UNAVAILABLE)

# The SDK puts the HTTP status first: "403 PERMISSION_DENIED. ...". Only that
# leading number counts, never digits elsewhere in the text.
_LEADING_STATUS = re.compile(r"^\s*(\d{3})\b")

# Wording that means the key itself is unusable, whatever the model.
_BAD_KEY = ("api_key_invalid", "api key not valid", "invalid api key", "api key expired", "unauthenticated")
_QUOTA = ("resource_exhausted", "resource exhausted", "quota", "rate limit")
_REGION = ("location is not supported", "user location")
_BUSY = ("unavailable", "overloaded", "internal error", "deadline exceeded", "try again later")

# Issue #124: a 429 from Gemini carries google.rpc.RetryInfo with a retryDelay
# such as "53s". The SDK ignores it and backs off on its own schedule
# (googleapis/python-genai#1875), so it is read here. The value also tells a
# per-minute limit apart from a daily one: per-minute delays are tens of
# seconds, daily ones have been reported as hours ("10h17m5.72s").
_RETRY_INFO_TYPE = "google.rpc.RetryInfo"
_DURATION = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?$")


def parse_retry_duration(text: object) -> Optional[float]:
    """Seconds in a protobuf duration string, or None when it is not one.

    Accepts "53s", "46.13s" and "10h17m5.72s". A bare float() would choke on
    every form but the first.
    """
    if not isinstance(text, str):
        return None
    m = _DURATION.match(text.strip())
    if not m or not any(m.groups()):
        return None
    hours, minutes, seconds = m.groups()
    return int(hours or 0) * 3600 + int(minutes or 0) * 60 + float(seconds or 0)


def retry_after_seconds(error: BaseException) -> Optional[float]:
    """How long the server asked us to wait, or None when it did not say.

    google-genai puts the response JSON on APIError.details. Anything else
    (a plain exception, a details that is not a dict, no RetryInfo entry)
    means no answer, and the caller keeps its existing behaviour.
    """
    details = getattr(error, "details", None)
    if not isinstance(details, dict):
        return None
    # The envelope is not the same on every path, and APIError unwraps a
    # single-element list before storing it, so both shapes are scanned
    # rather than only the one that happens to carry an "error" key.
    bodies = [details]
    inner = details.get("error")
    if isinstance(inner, dict):
        bodies.append(inner)
    for body in bodies:
        for entry in body.get("details") or ():
            if not isinstance(entry, dict):
                continue
            # The type is a URL; match its last segment, so a different type
            # that merely contains this name is not mistaken for it.
            kind = str(entry.get("@type", "")).rsplit("/", 1)[-1]
            if kind == _RETRY_INFO_TYPE:
                seconds = parse_retry_duration(entry.get("retryDelay"))
                if seconds is not None:
                    return seconds
    return None



def _status(text: str) -> Optional[int]:
    m = _LEADING_STATUS.match(text)
    return int(m.group(1)) if m else None


def classify_gemini_error(error: object) -> str:
    """Maps an exception (or its text) from the Gemini SDK to an error code."""
    text = str(error).lower()
    status = _status(text)
    if any(x in text for x in _REGION):
        return REGION_UNSUPPORTED
    # Quota before "invalid": Google reports some quota errors with 403 too.
    if status == 429 or any(x in text for x in _QUOTA):
        return KEY_QUOTA
    if status == 401 or any(x in text for x in _BAD_KEY):
        return KEY_INVALID
    if status == 403 or "permission_denied" in text:
        # Could be the key, or just no access to one (preview) model; the
        # caller keeps trying other models, see is_definitely_bad_key.
        return KEY_INVALID
    if status == 404 or "not_found" in text or ("model" in text and ("not found" in text or "not supported" in text)):
        return MODEL_UNAVAILABLE
    if status in (500, 502, 503, 504) or any(x in text for x in _BUSY):
        return AI_BUSY
    return AI_FAILED


def is_definitely_bad_key(error: object) -> bool:
    """
    True only when the key itself is unusable (invalid, expired,
    unauthenticated). Every model would fail the same way, so there is no
    point trying the rest. A plain 403 is not enough: it can mean one model
    is off-limits while others work.
    """
    text = str(error).lower()
    return _status(text) == 401 or any(x in text for x in _BAD_KEY)


def most_relevant(codes: Iterable[str]) -> str:
    """The code to report when a fallback chain collected several."""
    seen = set(codes)
    return next((c for c in REPORT_PRIORITY if c in seen), AI_FAILED)


def error_event(code: str) -> dict:
    """The SSE error payload for a code."""
    return {"error": MESSAGES[code], "code": code, "status": STATUS[code]}
