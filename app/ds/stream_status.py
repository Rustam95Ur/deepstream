"""Latest per-camera decode health, published by the live pipeline thread."""

from __future__ import annotations

import threading
from typing import Any

_lock = threading.Lock()
_engine: Any | None = None


def bind(engine: Any) -> None:
    global _engine
    with _lock:
        _engine = engine


def unbind(engine: Any) -> None:
    global _engine
    with _lock:
        if _engine is engine:
            _engine = None


def snapshot() -> list[dict[str, Any]]:
    with _lock:
        engine = _engine
    if engine is None:
        return []
    rows = engine.stream_rows()
    return rows if isinstance(rows, list) else []
