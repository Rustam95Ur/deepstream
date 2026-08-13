"""Non-blocking history: in-memory queue + batched inserts off the GPU thread."""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from queue import Empty, Full, Queue
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError

from app.db import db_enabled, session_scope
from app.models import SendEventRow, TriggerEventRow

logger = logging.getLogger(__name__)

Kind = Literal["trigger", "send"]


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    return int(raw) if raw else default


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _slim_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "event_id": payload.get("event_id"),
        "camera_id": payload.get("camera_id"),
        "trigger_type": payload.get("trigger_type"),
        "category": payload.get("category"),
        "trigger_time": payload.get("trigger_time"),
        "node_id": payload.get("node_id"),
        "evidence": payload.get("evidence") or {},
    }
    for key in ("video_url", "video_key", "video_bucket", "source_video"):
        if payload.get(key):
            out[key] = payload[key]
    return out


class HistoryWriter:
    def __init__(self) -> None:
        self._queue: Queue[tuple[Kind, dict[str, Any]]] = Queue(
            maxsize=_env_int("NEXUS_DS_HISTORY_QUEUE", 20000)
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._dropped = 0
        self._batch = _env_int("NEXUS_DS_HISTORY_BATCH", 200)
        self._flush_s = max(50, _env_int("NEXUS_DS_HISTORY_FLUSH_MS", 200)) / 1000.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="history-writer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self._flush()

    def put(self, kind: Kind, row: dict[str, Any]) -> None:
        try:
            self._queue.put_nowait((kind, row))
        except Full:
            self._dropped += 1
            if self._dropped % 100 == 1:
                logger.error("history queue full, dropped=%s", self._dropped)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._flush()
            self._stop.wait(self._flush_s)

    def _drain(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        triggers: list[dict[str, Any]] = []
        sends: list[dict[str, Any]] = []
        while len(triggers) + len(sends) < self._batch:
            try:
                kind, row = self._queue.get_nowait()
            except Empty:
                break
            if kind == "trigger":
                triggers.append(row)
            else:
                sends.append(row)
        return triggers, sends

    def _flush(self) -> None:
        if not db_enabled():
            return
        triggers, sends = self._drain()
        if not triggers and not sends:
            return
        try:
            with session_scope(write=True) as session:
                if triggers:
                    session.execute(
                        pg_insert(TriggerEventRow).on_conflict_do_nothing(
                            index_elements=["event_id"]
                        ),
                        triggers,
                    )
                if sends:
                    session.execute(pg_insert(SendEventRow), sends)
        except SQLAlchemyError:
            logger.exception(
                "history batch insert failed, dropping %s rows",
                len(triggers) + len(sends),
            )


_writer: HistoryWriter | None = None


def get_history_writer() -> HistoryWriter:
    global _writer
    if _writer is None:
        _writer = HistoryWriter()
    return _writer


def record_trigger(payload: dict[str, Any]) -> None:
    if not db_enabled():
        return
    get_history_writer().put(
        "trigger",
        {
            "id": str(uuid4()),
            "created_at": _utcnow(),
            "event_id": str(payload.get("event_id") or ""),
            "camera_id": str(payload.get("camera_id") or ""),
            "trigger_type": str(payload.get("trigger_type") or ""),
            "category": str(payload.get("category") or "incident"),
            "evidence": payload.get("evidence") or {},
            "payload": _slim_payload(payload),
        },
    )


def record_send(
    *,
    event_id: str,
    sink: str,
    url: str = "",
    status: str = "ok",
    http_status: int | None = None,
    error: str = "",
) -> None:
    if not db_enabled():
        return
    get_history_writer().put(
        "send",
        {
            "id": str(uuid4()),
            "created_at": _utcnow(),
            "event_id": event_id,
            "sink": sink,
            "url": url,
            "status": status,
            "http_status": http_status,
            "error": (error or "")[:2000],
        },
    )
