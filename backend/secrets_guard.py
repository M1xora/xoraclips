"""
Where the Gemini key comes from, and how it is kept out of logs.

The key lives only in the backend environment (`GEMINI_API_KEY` in .env).
The browser never sends it; the owner pays for AI usage (issue #8).

Kept free of heavy imports so it can be tested in CI on its own.
"""
import logging
import os
import re
from typing import Any

REDACTED = "[REDACTED]"

_TRUE = {"1", "true", "yes", "on"}

# Google API key shapes, plus key-bearing URL parameters and headers.
_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"AQ\.[0-9A-Za-z_\-]{20,}"),
    re.compile(r"(?i)([?&](?:api_key|apikey|key)=)[^&\s\"'<>]+"),
    re.compile(r"(?i)(x-goog-api-key[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+"),
]


def get_gemini_key() -> str:
    """The Gemini key from the backend environment; the only source."""
    return os.environ.get("GEMINI_API_KEY", "").strip()


def is_mock_mode() -> bool:
    """Demo mode with sample data, switched on by MOCK_MODE in .env."""
    return os.environ.get("MOCK_MODE", "").strip().lower() in _TRUE


def redact(text: str) -> str:
    """Replaces the configured key and anything shaped like a key."""
    if not text:
        return text
    key = get_gemini_key()
    if len(key) >= 8:
        text = text.replace(key, REDACTED)
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
