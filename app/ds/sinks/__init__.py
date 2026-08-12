"""Trigger sinks: HTTP POST and log."""

from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class TriggerSink(Protocol):
    source_video: str | None

    def send(self, payload: dict[str, Any]) -> str | None: ...


class LogSink:
    def __init__(self, *, source_video: str | None = None) -> None:
        self.source_video = source_video

    def send(self, payload: dict[str, Any]) -> str | None:
        logger.info(
            "TRIGGER log camera=%s type=%s event=%s",
            payload.get("camera_id"),
            payload.get("trigger_type"),
            payload.get("event_id"),
        )
        return None


class CompositeSink:
    def __init__(
        self,
        sinks: list[Any],
        *,
        source_video: str | None = None,
        max_triggers: int | None = None,
    ) -> None:
        self.sinks = sinks
        self.source_video = source_video
        self.max_triggers = max_triggers
        self._sent = 0

    def send(self, payload: dict[str, Any]) -> str | None:
        if self.max_triggers is not None and self._sent >= self.max_triggers:
            logger.info("max_triggers reached — drop %s", payload.get("trigger_type"))
            return None
        self._sent += 1
        if self.source_video and "source_video" not in payload:
            payload["source_video"] = self.source_video
        last: str | None = None
        for sink in self.sinks:
            try:
                last = sink.send(payload) or last
            except Exception:
                logger.exception("sink %s failed", type(sink).__name__)
        return last
