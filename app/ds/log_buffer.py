"""In-memory ring of recent WARNING+ logs for the console."""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any

_MAX = 80
_lock = threading.Lock()
_lines: deque[dict[str, Any]] = deque(maxlen=_MAX)
_handler: logging.Handler | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def note(message: str, *, level: str = "WARNING", logger_name: str = "app") -> None:
    text = (message or "").strip()
    if not text:
        return
    row = {
        "ts": _utcnow(),
        "level": (level or "WARNING").upper(),
        "logger": logger_name,
        "message": text[:800],
    }
    with _lock:
        _lines.append(row)


def snapshot(limit: int = 40) -> list[dict[str, Any]]:
    n = max(1, min(int(limit), _MAX))
    with _lock:
        rows = list(_lines)[-n:]
    rows.reverse()
    return rows


class _BufferHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.WARNING:
            return
        name = record.name or ""
        if not (
            name.startswith("app")
            or name.startswith("nexus_deepstream")
            or name.startswith("gst")
        ):
            return
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        note(msg, level=record.levelname, logger_name=name)


def install(logger: logging.Logger | None = None) -> None:
    global _handler
    target = logger or logging.getLogger()
    with _lock:
        if _handler is not None:
            return
        handler = _BufferHandler()
        handler.setLevel(logging.WARNING)
        handler.setFormatter(logging.Formatter("%(message)s"))
        target.addHandler(handler)
        _handler = handler
