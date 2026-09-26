"""Outbound webhook job enqueue / resend / retry."""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from app.db import db_enabled, session_scope
from app.ds.payload import (
    CLIP_META_KEY,
    clip_from_payload,
    has_clip_source,
    missing_video_reason,
    normalize_payload,
    requires_video,
)
from app.campus import to_smartbox_ingest
from app.history import record_send
from app.models import OutboundJobRow, TriggerEventRow
from app.storage import get_store
from app.timeutil import utcnow
from app.webhooks.repository import list_enabled_webhooks

logger = logging.getLogger(__name__)


def enqueue_payload(payload: dict[str, Any], *, reason: str = "trigger") -> int:
    from app.billing import license_lock_detail, license_ok

    body = normalize_payload(payload)
    event_id = str(body.get("event_id") or "")
    if not license_ok():
        record_send(
            event_id=event_id,
            sink="webhook",
            url="",
            status="skipped",
            error=license_lock_detail(),
        )
        return 0
    if requires_video(body) and not has_clip_source(body):
        why = missing_video_reason(body) or "video required"
        record_send(
            event_id=event_id,
            sink="webhook",
            url="",
            status="skipped",
            error=why,
        )
        logger.warning(
            "skip webhook enqueue event=%s reason=%s: %s", event_id, reason, why
        )
        return 0
    outbound = to_smartbox_ingest(body)
    clip = clip_from_payload(body)
    meta = {k: v for k, v in clip.items() if v}
    if meta:
        outbound[CLIP_META_KEY] = meta
    settings = get_store().get_settings()
    if not settings.enable_http_sink:
        record_send(
            event_id=event_id,
            sink="webhook",
            url="",
            status="skipped",
            error="http sink disabled",
        )
        return 0
    if not db_enabled():
        record_send(
            event_id=event_id,
            sink="webhook",
            url="",
            status="skipped",
            error="database unavailable",
        )
        return 0
    hooks = list_enabled_webhooks()
    if not hooks:
        record_send(
            event_id=event_id,
            sink="webhook",
            url="",
            status="skipped",
            error="no webhooks",
        )
        return 0
    now = utcnow()
    n = 0
    with session_scope(write=True) as session:
        for hook in hooks:
            session.add(
                OutboundJobRow(
                    id=str(uuid4()),
                    event_id=event_id,
                    webhook_id=hook.id,
                    url=hook.url,
                    payload=outbound,
                    attempts=0,
                    max_attempts=hook.max_attempts,
                    status="pending",
                    last_error="",
                    http_status=None,
                    next_attempt_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            n += 1
    logger.info("queued %s webhook job(s) event=%s reason=%s", n, event_id, reason)
    return n


def resend_event(event_id: str) -> int:
    eid = (event_id or "").strip()
    if not eid or not db_enabled():
        return 0
    with session_scope(write=False) as session:
        row = session.scalar(
            select(TriggerEventRow).where(TriggerEventRow.event_id == eid)
        )
        payload = dict(row.payload or {}) if row else {}
    if not payload:
        return 0
    payload["event_id"] = eid
    return enqueue_payload(payload, reason="resend")


def retry_job(job_id: str) -> OutboundJobRow | None:
    if not db_enabled():
        return None
    now = utcnow()
    with session_scope(write=True) as session:
        row = session.get(OutboundJobRow, job_id)
        if row is None:
            return None
        row.status = "pending"
        row.attempts = 0
        row.last_error = ""
        row.http_status = None
        row.next_attempt_at = now
        row.updated_at = now
        session.flush()
        session.expunge(row)
        return row
