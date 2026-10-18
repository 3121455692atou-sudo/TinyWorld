"""Local request diagnostics. Credentials and image bytes never enter the log."""
from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import traceback
from urllib.parse import urlsplit, urlunsplit

from app.core.config import ROOT_DIR

trace_context: ContextVar[dict] = ContextVar("request_trace", default={})
TRACE_PATH = ROOT_DIR / "logs" / "model-requests.jsonl"
_logger = logging.getLogger("tinyworld.requests")
_logger.setLevel(logging.INFO)
_logger.propagate = False


class PrivateRotatingHandler(RotatingFileHandler):
    def _open(self):
        fd = os.open(self.baseFilename, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        return os.fdopen(fd, "a", encoding="utf-8")


def safe_url(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc.split("@")[-1], parsed.path, "", ""))


def _clean(value):
    if isinstance(value, dict):
        return {str(k): ("[redacted]" if any(x in str(k).lower() for x in ("api_key", "authorization", "cookie", "secret", "password")) else _clean(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, bytes):
        return f"[binary {len(value)} bytes]"
    if isinstance(value, str):
        if len(value) > 1024 and re.fullmatch(r"[A-Za-z0-9+/=]+", value):
            return "[base64 data omitted]"
        value = re.sub(r"data:image/[^;]+;base64,[A-Za-z0-9+/=\s]+", "[image data omitted]", value)
        value = re.sub(r"(?i)Bearer\s+[^\s\"']+|\bsk-[A-Za-z0-9_-]+", "[redacted]", value)
        return re.sub(r"https?://[^\s\"'<>]+", lambda m: safe_url(m.group()), value)
    return value


def trace(stage: str, **fields) -> None:
    if not _logger.handlers:
        TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(TRACE_PATH, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        os.close(fd)
        handler = PrivateRotatingHandler(TRACE_PATH, maxBytes=20_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        _logger.addHandler(handler)
    _logger.info(json.dumps(_clean({"time": datetime.now(timezone.utc).isoformat(), **trace_context.get(), "stage": stage, **fields}), ensure_ascii=False))


def trace_failure(stage: str, exc: BaseException, **fields) -> None:
    # SQLAlchemy exceptions can stringify SQL parameters (including credentials).
    # Log frames and the exception class, never a database parameter dump.
    error = str(exc)[:2000] if not type(exc).__module__.startswith("sqlalchemy") else "Database operation failed; inspect stack locations."
    trace(stage, error_type=type(exc).__name__, error=error,
          stack=[{"file": f.filename, "line": f.lineno, "function": f.name} for f in traceback.extract_tb(exc.__traceback__)], **fields)
