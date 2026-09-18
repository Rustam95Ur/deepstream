"""JSON structured logging for Docker → Loki / Grafana.

Env:
  NEXUS_DS_LOG_LEVEL   DEBUG|INFO|WARNING|ERROR  (default INFO)
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

_RESERVED = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
        "taskName",
    }
)

_context: dict[str, Any] = {
    "service": "nexus-deepstream",
    "role": "",
    "node_id": "",
}
_configured = False


def bind_context(**fields: Any) -> None:
    """Update process-wide fields (service, role, node_id, …) on every log line."""
    for key, value in fields.items():
        if value is None:
            _context.pop(key, None)
        else:
            text = str(value).strip()
            if text:
                _context[key] = text
            else:
                _context.pop(key, None)


def log_extra(**fields: Any) -> dict[str, Any]:
    """Build ``extra=`` for structured fields (camera_id, event_id, …)."""
    out: dict[str, Any] = {}
    for key, value in fields.items():
        if value is None or key in _RESERVED:
            continue
        if isinstance(value, (str, int, float, bool, dict, list)):
            out[key] = value
        else:
            out[key] = str(value)
    return out


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in _context.items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line — Promtail/Alloy/Loki friendly."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in _context.items():
            payload.setdefault(key, value)
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            if key in payload:
                continue
            if value is None:
                continue
            if isinstance(value, (str, int, float, bool)):
                payload[key] = value
            else:
                try:
                    json.dumps(value)
                    payload[key] = value
                except (TypeError, ValueError):
                    payload[key] = str(value)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _parse_level(raw: str | None) -> int:
    name = (raw or "INFO").strip().upper()
    return getattr(logging, name, logging.INFO)


def configure_logging(
    *,
    service: str,
    role: str = "",
    level: str | None = None,
    force: bool = False,
) -> None:
    """Configure root logging once per process (always JSON). Safe at import time."""
    global _configured
    if _configured and not force:
        bind_context(service=service, role=role or None)
        return

    level_name = level if level is not None else os.environ.get("NEXUS_DS_LOG_LEVEL")
    log_level = _parse_level(level_name)

    bind_context(service=service, role=role or None)

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(log_level)
    handler.addFilter(_ContextFilter())
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # Keep library noise down; app.* / nexus_deepstream.* stay at root level.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "asyncio"):
        logging.getLogger(name).setLevel(max(log_level, logging.INFO))

    _configured = True
