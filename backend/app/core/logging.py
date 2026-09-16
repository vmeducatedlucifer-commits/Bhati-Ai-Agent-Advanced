"""Structured logging setup."""

from __future__ import annotations

import logging
import re
import sys
import time

from app.core.config import settings

_LEVEL_COLORS = {
    "DEBUG": "\x1b[38;5;244m",
    "INFO": "\x1b[38;5;39m",
    "WARNING": "\x1b[38;5;214m",
    "ERROR": "\x1b[38;5;196m",
    "CRITICAL": "\x1b[48;5;196;38;5;231m",
}
_RESET = "\x1b[0m"


class ConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        color = _LEVEL_COLORS.get(record.levelname, "")
        ts = time.strftime("%H:%M:%S", time.localtime(record.created))
        prefix = f"{color}{record.levelname:<8}{_RESET}" if color else f"{record.levelname:<8}"
        msg = record.getMessage()
        line = f"{ts} {prefix} {record.name:<28} {msg}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


# Secrets must never reach log storage: bearer JWTs ride in query strings
# (EventSource/WebSocket clients cannot set headers), so uvicorn's access log
# would otherwise persist them verbatim. Redact before any handler emits.
_SECRET_QUERY_RE = re.compile(r"((?:token|ticket)=)([^&\s\"']+)", re.IGNORECASE)
_BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+")

REDACTED = "[REDACTED]"


def _redact(text: str) -> str:
    text = _SECRET_QUERY_RE.sub(rf"\1{REDACTED}", text)
    return _BEARER_RE.sub(rf"\1{REDACTED}", text)


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = _redact(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: (_redact(v) if isinstance(v, str) else v) for k, v in record.args.items()}
                elif isinstance(record.args, tuple):
                    record.args = tuple(_redact(a) if isinstance(a, str) else a for a in record.args)
        except Exception:
            pass
        return True


def setup_logging() -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ConsoleFormatter())
    root.addHandler(handler)
    root.setLevel(settings.LOG_LEVEL.upper())
    # Belt and suspenders: the filter lives on the root logger (covers every
    # app record) AND directly on uvicorn's access/error loggers, which bypass
    # the root handlers with their own.
    redaction = SecretRedactionFilter()
    root.addFilter(redaction)
    for uv in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(uv).addFilter(redaction)

    for noisy in ("httpx", "httpcore", "docker", "urllib3", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
