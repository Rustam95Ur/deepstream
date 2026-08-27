"""Enqueue trigger payload to the webhook retry queue."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class OutboundEnqueueSink:
    def __init__(self, *, source_video: str | None = None) -> None:
        self.source_video = source_video

    def send(self, payload: dict[str, Any]) -> str | None:
        from app.ds.payload import normalize_payload
        from app.webhooks import enqueue_payload

        body = normalize_payload(payload)
        payload.update(body)
        try:
            enqueue_payload(body)
        except Exception:
            logger.exception(
                "failed to enqueue webhooks event=%s", body.get("event_id")
            )
        return str(body.get("event_id") or "") or None
