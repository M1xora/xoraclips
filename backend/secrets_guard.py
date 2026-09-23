"""
Where the Gemini key comes from, and how it is kept out of logs.

The key comes ONLY from the user, in the `X-Gemini-Api-Key` request header
(issue #12): users pay for their own AI usage. There is no server key in
.env. Keys in URLs or request bodies are ignored.

While a request is using a key, that exact key is registered for THAT
request only (a context variable), so its log lines and messages have it
scrubbed whatever its shape, and no other user's output is touched.
Known Google key shapes are scrubbed at all times as a backstop.

Kept free of heavy imports so it can be tested in CI on its own.
"""
import logging
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Optional

REDACTED = "[REDACTED]"

# The request header that carries the user's key.
GEMINI_KEY_HEADER = "X-Gemini-Api-Key"

_TRUE = {"1", "true", "yes", "on"}

# Google API key shapes, plus key-bearing URL parameters and headers.
_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"AQ\.[0-9A-Za-z_\-]{20,}"),
    re.compile(r"(?i)([?&](?:api_key|apikey|key)=)[^&\s\"'<>]+"),
    re.compile(r"(?i)((?:x-goog-api-key|x-gemini-api-key)[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+"),
]

# Keys in use by the CURRENT request. A context variable follows the request
# through its awaits and into asyncio.to_thread workers, and never leaks into
# another request, so one user cannot make the app scrub text in someone
# else's results (e.g. by sending "https://" as their "key").
_request_secrets: ContextVar[tuple] = ContextVar("gemini_request_secrets", default=())
# Anything shorter is not a key; scrubbing it would only garble the user's own output.
_MIN_SECRET_LEN = 4


def user_key_from_header(value: Optional[str]) -> Optional[str]:
    """The user's key from the request header, or None when absent/blank."""
    key = (value or "").strip()
    return key or None


def is_mock_mode() -> bool:
    """Demo mode with sample data, switched on by MOCK_MODE in .env."""
    return os.environ.get("MOCK_MODE", "").strip().lower() in _TRUE


@contextmanager
def tracked_secret(key: Optional[str]) -> Iterator[None]:
    """Scrub this exact key from this request's logs and payloads while the block runs."""
    if not key or len(key) < _MIN_SECRET_LEN:
        yield
        return
    token = _request_secrets.set(_request_secrets.get() + (key,))
    try:
        yield
    finally:
        try:
            _request_secrets.reset(token)
        except ValueError:
            # A streaming response closed from another context (client
            # disconnected); that context never saw the key anyway.
            pass


def redact(text: str) -> str:
    """Replaces the current request's keys and anything shaped like a key."""
    if not text:
        return text
    for secret in sorted(_request_secrets.get(), key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    for pattern in _PATTERNS:
        text = pattern.sub(lambda m: (m.group(1) if m.groups() else "") + REDACTED, text)
    return text


def _redact_arg(arg: Any) -> Any:
    if isinstance(arg, str):
        return redact(arg)
    if isinstance(arg, (int, float, bool)) or arg is None:
        return arg
    # Objects such as exceptions: keep them unless their text leaks a key.
    text = str(arg)
    cleaned = redact(text)
    return cleaned if cleaned != text else arg


def redact_data(value: Any) -> Any:
    """
    Scrubs every string inside a JSON-like value. Used on API payloads
    BEFORE serialising: redacting the serialised text could cut through an
    escaped quote and leave invalid JSON.
    """
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_data(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_data(v) for v in value]
    return value


def scrub_record(record: logging.LogRecord) -> None:
    """
    Removes keys from a log record in place: arguments, message, exception
    and stack text.

    Arguments are scrubbed one by one and kept as arguments, because
    uvicorn's access formatter unpacks its five (client, method, path,
    version, status) itself. The message template is only rewritten when
    it leaks a key on its own; if it also has arguments, the message is
    rendered first so placeholders and arguments cannot fall out of step.
    """
    if isinstance(record.args, tuple):
        record.args = tuple(_redact_arg(a) for a in record.args)
    elif isinstance(record.args, dict):
        record.args = {k: _redact_arg(v) for k, v in record.args.items()}

    msg = record.msg
    text = msg if isinstance(msg, str) else str(msg)
    if redact(text) != text:
        if record.args:
            try:
                rendered = record.getMessage()
            except Exception:
                rendered = text
            record.msg, record.args = redact(rendered), None
        else:
            record.msg = redact(text)

    if record.exc_info and not record.exc_text:
        record.exc_text = logging.Formatter().formatException(record.exc_info)
    if record.exc_text:
        record.exc_text = redact(record.exc_text)
    if record.stack_info:
        record.stack_info = redact(record.stack_info)


class RedactingFilter(logging.Filter):
    """A logging filter that runs scrub_record, for handlers set up by hand."""

    def filter(self, record: logging.LogRecord) -> bool:
        scrub_record(record)
        return True


def install_log_redaction() -> None:
    """
    Scrubs every log record at the moment it is created, whatever logger or
    handler it goes to: the app, uvicorn's access log, libraries such as
    httpx or google-genai, and handlers added later (a log file, a test
    capture). Done by wrapping the process-wide log record factory.
    Safe to call repeatedly.
    """
    current = logging.getLogRecordFactory()
    if getattr(current, "_redacting", False):
        return

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = current(*args, **kwargs)
        scrub_record(record)
        return record

    factory._redacting = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)
