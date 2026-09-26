"""Outbound webhook delivery and job claim/process."""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select, text

from app.campus import to_smartbox_ingest
from app.db import db_enabled, session_scope
from app.ds.payload import (
    CLIP_META_KEY,
    clip_from_payload,
    missing_video_reason,
    requires_video,
)
from app.ds.sinks.http_sink import post_json, post_multipart
from app.history import record_send
from app.logging_config import log_extra
from app.minio_store import get_minio_store
from app.models import OutboundJobRow, TriggerEventRow, WebhookRow
from app.storage import get_store
from app.timeutil import utcnow
from app.webhooks.models import Webhook, from_row

logger = logging.getLogger(__name__)

MAX_BACKOFF_S = 60.0
VIDEO_POST_TIMEOUT_S = 120.0

_SKIP_DELIVERY = frozenset({"webhook disabled", "http sink disabled"})

# Inline status literals so Postgres can use ix_outbound_jobs_due.
# Select id only: loading payload JSONB under FOR UPDATE timed out at 5s.
_CLAIM_SQL = text(
    """
    WITH due AS (
        SELECT id
        FROM outbound_jobs
        WHERE status IN ('pending', 'retrying')
          AND next_attempt_at <= :now
        ORDER BY next_attempt_at, created_at
        LIMIT :limit
        FOR UPDATE SKIP LOCKED
    )
    UPDATE outbound_jobs AS j
    SET status = 'retrying',
        next_attempt_at = :claim_at,
        updated_at = :now
    FROM due
    WHERE j.id = due.id
    RETURNING j.id
    """
)


def _backoff_s(attempts: int) -> float:
    return float(min(MAX_BACKOFF_S, 2 ** max(0, attempts - 1)))


def _clip_filename(event_id: str) -> str:
    safe = "".join(
        ch if ch.isalnum() or ch in "-_." else "_" for ch in (event_id or "clip")
    )[:80]
    return f"{safe or 'clip'}.mp4"


def clip_bytes_for_event(
    event_id: str,
    payload: dict[str, Any] | None = None,
) -> tuple[bytes | None, str, str]:
    """Load incident MP4. Returns ``(data, filename, reason)``; reason set on failure."""
    raw = payload if isinstance(payload, dict) else {}
    nested = raw.get(CLIP_META_KEY) if isinstance(raw.get(CLIP_META_KEY), dict) else {}
    clip = clip_from_payload(raw)
    path = str(nested.get("path") or clip.get("path") or "").strip()
    key = str(nested.get("key") or clip.get("key") or "").strip()
    why: list[str] = []
    filename = _clip_filename(event_id)

    if path:
        file_path = Path(path)
        if file_path.is_file():
            try:
                data = file_path.read_bytes()
            except OSError:
                logger.exception("failed to read clip %s", file_path)
                why.append(f"cannot read local file: {path}")
            else:
                if data:
                    return data, filename, ""
                why.append(f"local clip is empty: {path}")
        else:
            why.append(f"local file missing: {path}")
    else:
        why.append("no local clip path")

    if not key and event_id and db_enabled():
        with session_scope(write=False) as session:
            row = session.scalar(
                select(TriggerEventRow).where(TriggerEventRow.event_id == event_id)
            )
            hist = dict(row.payload or {}) if row else {}
        hist_clip = clip_from_payload(hist)
        key = hist_clip.get("key") or key
        if not path:
            path = hist_clip.get("path") or ""
            file_path = Path(path) if path else None
            if file_path is not None and file_path.is_file():
                try:
                    data = file_path.read_bytes()
                except OSError:
                    logger.exception("failed to read clip %s", file_path)
                    why.append(f"cannot read history file: {path}")
                else:
                    if data:
                        return data, filename, ""
                    why.append(f"history clip is empty: {path}")
            elif path:
                why.append(f"history local file missing: {path}")

    if key:
        data = get_minio_store().get_object_bytes(key)
        if data:
            return data, filename, ""
        why.append(f"minio read failed key={key}")
    else:
        why.append("no minio key")

    return None, filename, "; ".join(why)


def _delivery_skip_reason(job: OutboundJobRow) -> tuple[Webhook | None, str]:
    """Return ``(hook, reason)``. Non-empty reason means do not POST."""
    if not get_store().get_settings().enable_http_sink:
        return None, "http sink disabled"
    hook: Webhook | None = None
    with session_scope(write=False) as session:
        row = session.get(WebhookRow, job.webhook_id)
        if row is not None:
            hook = from_row(row)
    if hook is None or not hook.enabled or not (hook.url or "").strip():
        return hook, "webhook disabled"
    return hook, ""


def deliver(job: OutboundJobRow) -> tuple[bool, int | None, str]:
    hook, skip = _delivery_skip_reason(job)
    if skip:
        logger.info(
            "webhook skip event=%s reason=%s url=%s",
            job.event_id,
            skip,
            job.url,
        )
        return False, None, skip
    url = hook.url if hook else job.url
    timeout = hook.timeout_sec if hook else 5.0
    outbound = to_smartbox_ingest(job.payload or {})
    outbound.pop(CLIP_META_KEY, None)
    event_id = str(job.event_id or "")
    headers = {
        "User-Agent": "nexus-deepstream/0.1",
    }
    if event_id:
        headers["X-Nexus-Event-Id"] = event_id

    clip_data, filename, clip_why = clip_bytes_for_event(
        event_id, job.payload if isinstance(job.payload, dict) else None
    )
    if requires_video(outbound) or requires_video(job.payload or {}):
        if not clip_data:
            why = clip_why or missing_video_reason(job.payload or {}) or "video required"
            logger.error("webhook skip video event=%s reason=%s", event_id, why)
            return False, None, why
        send_timeout = max(float(timeout), VIDEO_POST_TIMEOUT_S)
        logger.info(
            "webhook multipart event=%s bytes=%s file=%s url=%s",
            event_id,
            len(clip_data),
            filename,
            url,
        )
        return post_multipart(
            url,
            fields={"payload": json.dumps(outbound, ensure_ascii=False)},
            files={"video": (filename, clip_data, "video/mp4")},
            headers=headers,
            timeout_sec=send_timeout,
        )

    why = "video not required (stream_silent / no algo_model)"
    logger.info("webhook json event=%s reason=%s url=%s", event_id, why, url)
    body = json.dumps(outbound, ensure_ascii=False).encode("utf-8")
    return post_json(url, body, headers=headers, timeout_sec=timeout)


def _non_retryable(error: str) -> bool:
    return (error or "").strip().lower() in _SKIP_DELIVERY


def claim_jobs(limit: int = 8) -> list[str]:
    now = utcnow()
    claim_at = now + timedelta(seconds=max(30, int(VIDEO_POST_TIMEOUT_S) + 15))
    with session_scope(write=True) as session:
        rows = session.execute(
            _CLAIM_SQL,
            {"now": now, "claim_at": claim_at, "limit": int(limit)},
        )
        return [str(row[0]) for row in rows]


def process_job(job_id: str) -> None:
    with session_scope(write=False) as session:
        job = session.get(OutboundJobRow, job_id)
        if job is None:
            return
        payload = dict(job.payload or {})
        snapshot = OutboundJobRow(
            id=job.id,
            event_id=job.event_id,
            webhook_id=job.webhook_id,
            url=job.url,
            payload=payload,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
            status=job.status,
            last_error=job.last_error,
            http_status=job.http_status,
            next_attempt_at=job.next_attempt_at,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )
    ok, http_status, error = deliver(snapshot)
    now = utcnow()
    with session_scope(write=True) as session:
        row = session.get(OutboundJobRow, job_id)
        if row is None:
            return
        row.attempts = int(row.attempts or 0) + 1
        row.http_status = http_status
        row.updated_at = now
        if ok:
            row.status = "ok"
            row.last_error = ""
            row.next_attempt_at = now
        else:
            row.last_error = (error or "delivery failed")[:2000]
            if _non_retryable(error) or row.attempts >= max(1, int(row.max_attempts or 1)):
                row.status = "dead"
                row.next_attempt_at = now
            else:
                row.status = "retrying"
                row.next_attempt_at = now + timedelta(seconds=_backoff_s(row.attempts))
        event_id = row.event_id
        url = row.url
        skipped = (not ok) and _non_retryable(row.last_error)
        status = "ok" if ok else ("skipped" if skipped else "error")
        attempts = row.attempts
        last_error = row.last_error
        final_status = row.status
    record_send(
        event_id=event_id,
        sink="webhook",
        url=url,
        status=status,
        http_status=http_status,
        error="" if ok else last_error,
    )
    if ok:
        logger.info(
            "webhook ok",
            extra=log_extra(
                event_id=event_id,
                attempt=attempts,
                webhook_url=url,
                http_status=http_status,
            ),
        )
        meta = payload.get(CLIP_META_KEY) if isinstance(payload.get(CLIP_META_KEY), dict) else {}
        path = str((meta or {}).get("path") or "").strip()
        key = str((meta or {}).get("key") or "").strip()
        # Keep the local file when MinIO has no key — resend still needs it.
        if path and key:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "failed to remove local clip",
                    extra=log_extra(event_id=event_id, clip_path=path),
                )
    elif final_status == "dead":
        log = logger.info if _non_retryable(last_error) else logger.error
        log(
            "webhook dead",
            extra=log_extra(
                event_id=event_id,
                attempt=attempts,
                webhook_url=url,
                error=last_error,
            ),
        )
    else:
        logger.warning(
            "webhook retry",
            extra=log_extra(
                event_id=event_id,
                attempt=attempts,
                webhook_url=url,
                error=last_error,
            ),
        )
