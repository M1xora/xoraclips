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


class RedactingFilter(logging.Filter):
    """
    Scrubs keys from every log record: the message, each argument, and the
    exception text.

    Arguments are redacted one by one rather than merged into the message,
    because uvicorn's access formatter unpacks its five arguments
    (client, method, path, version, status) itself.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_redact_arg(a) for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: _redact_arg(v) for k, v in record.args.items()}
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        return True


_FILTER = RedactingFilter()
_LOGGERS = (
    "", "uvicorn", "uvicorn.error", "uvicorn.access", "httpx", "google_genai", "google",
    # The app's own loggers: filtered at the source, so even a handler added
    # later (a log file, a test capture) only ever sees scrubbed records.
    "cheat-clip-pro", "cheat-clip-pro.video-engine",
)


def install_log_redaction() -> None:
    """
    Attaches the filter to the relevant loggers and all of their handlers.
    A logger's own filter only sees records created on that logger, so the
    handlers are covered too, for records propagating up from libraries.
    Safe to call repeatedly; call again after uvicorn configures logging.
    """
    for name in _LOGGERS:
        lg = logging.getLogger(name)
        if _FILTER not in lg.filters:
            lg.addFilter(_FILTER)
        for handler in lg.handlers:
            if _FILTER not in handler.filters:
                handler.addFilter(_FILTER)
