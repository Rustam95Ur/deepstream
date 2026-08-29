"""Webhook registry and outbound retry queue."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.db import db_enabled, session_scope
from app.ds.payload import (
    CLIP_META_KEY,
    clip_from_payload,
    has_clip_source,
    missing_video_reason,
    normalize_payload,
    requires_video,
    to_smartbox_ingest,
)
from app.ds.sinks.http_sink import post_json, post_multipart
from app.history import record_send
from app.minio_store import get_minio_store
from app.models import OutboundJobRow, TriggerEventRow, WebhookRow
from app.settings import NodeSettings
from app.storage import get_store
from app.web.passwords import hash_password, verify_password

logger = logging.getLogger(__name__)

OPEN_STATUSES = ("pending", "retrying")
MAX_BACKOFF_S = 60.0
VIDEO_POST_TIMEOUT_S = 120.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class Webhook:
    id: str
    name: str
    url: str
    enabled: bool
    login: str
    auth_configured: bool
    timeout_sec: float
    max_retries: int
    created_at: datetime
    updated_at: datetime

    @property
    def max_attempts(self) -> int:
        return max(1, int(self.max_retries) + 1)


def _from_row(row: WebhookRow) -> Webhook:
    return Webhook(
        id=row.id,
        name=row.name or "",
        url=(row.url or "").strip(),
        enabled=bool(row.enabled),
        login=(row.login or "").strip(),
        auth_configured=bool(
            (row.login or "").strip() and (row.password_hash or "").strip()
        ),
        timeout_sec=float(row.timeout_sec or 5.0),
        max_retries=int(row.max_retries or 0),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def list_webhooks() -> list[Webhook]:
    if not db_enabled():
        return []
    with session_scope(write=False) as session:
        rows = session.scalars(
            select(WebhookRow).order_by(WebhookRow.created_at, WebhookRow.id)
        ).all()
        return [_from_row(r) for r in rows]


def list_enabled_webhooks() -> list[Webhook]:
    return [w for w in list_webhooks() if w.enabled and w.url]


def get_webhook(webhook_id: str) -> Webhook | None:
    if not db_enabled():
        return None
    with session_scope(write=False) as session:
        row = session.get(WebhookRow, webhook_id)
        return _from_row(row) if row else None


def authenticate_webhook_login(login: str, password: str) -> Webhook | None:
    name = (login or "").strip()
    secret = password or ""
    if not name or not secret:
        return None
    if not db_enabled():
        return None
    with session_scope(write=False) as session:
        row = session.scalar(
            select(WebhookRow).where(
                func.lower(WebhookRow.login) == name.lower(),
                WebhookRow.enabled.is_(True),
            )
        )
        if row is None or not (row.password_hash or "").strip():
            return None
        if not verify_password(secret, row.password_hash):
            return None
        return _from_row(row)


def create_webhook(
    *,
    name: str,
    url: str,
    enabled: bool = True,
    login: str = "",
    password: str = "",
    timeout_sec: float = 5.0,
    max_retries: int = 5,
) -> Webhook:
    now = _utcnow()
    login_value = (login or "").strip()
    with session_scope(write=True) as session:
        row = WebhookRow(
            id=str(uuid4()),
            name=(name or "").strip() or "webhook",
            url=(url or "").strip(),
            enabled=bool(enabled),
            login=login_value,
            password_hash=hash_password(password) if password else "",
            timeout_sec=float(timeout_sec),
            max_retries=int(max_retries),
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.flush()
        return _from_row(row)


def update_webhook(
    webhook_id: str,
    *,
    name: str,
    url: str,
    enabled: bool,
    timeout_sec: float,
    max_retries: int,
    login: str | None = None,
    password: str | None = None,
) -> Webhook | None:
    with session_scope(write=True) as session:
        row = session.get(WebhookRow, webhook_id)
        if row is None:
            return None
        if login is not None:
            login_value = login.strip()
            row.login = login_value
        row.name = (name or "").strip() or row.name
        row.url = (url or "").strip()
        row.enabled = bool(enabled)
        row.timeout_sec = float(timeout_sec)
        row.max_retries = int(max_retries)
        if password:
            row.password_hash = hash_password(password)
        row.updated_at = _utcnow()
        session.flush()
        return _from_row(row)


def delete_webhook(webhook_id: str) -> bool:
    with session_scope(write=True) as session:
        row = session.get(WebhookRow, webhook_id)
        if row is None:
            return False
        session.delete(row)
        return True


def seed_webhooks_from_settings(settings: NodeSettings | None = None) -> None:
    if not db_enabled():
        return
    cfg = settings or get_store().get_settings()
    url = (cfg.triggers_url or "").strip()
    with session_scope(write=True) as session:
        count = session.scalar(select(func.count()).select_from(WebhookRow)) or 0
        if count:
            return
        if not url:
            return
        now = _utcnow()
        session.add(
            WebhookRow(
                id=str(uuid4()),
                name="default",
                url=url,
                enabled=True,
                hmac_secret="",
                timeout_sec=float(cfg.triggers_timeout_sec or 5.0),
                max_retries=5,
                created_at=now,
                updated_at=now,
            )
        )
        logger.info("seeded webhook from settings.triggers_url")


def _backoff_s(attempts: int) -> float:
    return float(min(MAX_BACKOFF_S, 2 ** max(0, attempts - 1)))


def enqueue_payload(payload: dict[str, Any], *, reason: str = "trigger") -> int:
    body = normalize_payload(payload)
    event_id = str(body.get("event_id") or "")
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
    now = _utcnow()
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
    now = _utcnow()
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


def _clip_bytes_for_event(
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


def _clip_filename(event_id: str) -> str:
    safe = "".join(
        ch if ch.isalnum() or ch in "-_." else "_" for ch in (event_id or "clip")
    )[:80]
    return f"{safe or 'clip'}.mp4"


def _delivery_skip_reason(job: OutboundJobRow) -> tuple[Webhook | None, str]:
    """Return ``(hook, reason)``. Non-empty reason means do not POST."""
    if not get_store().get_settings().enable_http_sink:
        return None, "http sink disabled"
    hook: Webhook | None = None
    with session_scope(write=False) as session:
        row = session.get(WebhookRow, job.webhook_id)
        if row is not None:
            hook = _from_row(row)
    if hook is None or not hook.enabled or not (hook.url or "").strip():
        return hook, "webhook disabled"
    return hook, ""


def _deliver(job: OutboundJobRow) -> tuple[bool, int | None, str]:
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

    clip_data, filename, clip_why = _clip_bytes_for_event(
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


_SKIP_DELIVERY = frozenset({"webhook disabled", "http sink disabled"})


def _non_retryable(error: str) -> bool:
    return (error or "").strip().lower() in _SKIP_DELIVERY


def _claim_jobs(limit: int = 8) -> list[str]:
    now = _utcnow()
    ids: list[str] = []
    with session_scope(write=True) as session:
        rows = list(
            session.scalars(
                select(OutboundJobRow)
                .where(OutboundJobRow.status.in_(OPEN_STATUSES))
                .where(OutboundJobRow.next_attempt_at <= now)
                .order_by(OutboundJobRow.next_attempt_at, OutboundJobRow.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
        )
        claim_at = now + timedelta(seconds=max(30, int(VIDEO_POST_TIMEOUT_S) + 15))
        for row in rows:
            row.status = "retrying"
            row.next_attempt_at = claim_at
            row.updated_at = now
            ids.append(row.id)
    return ids


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
    ok, http_status, error = _deliver(snapshot)
    now = _utcnow()
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
        logger.info("webhook ok event=%s attempt=%s url=%s", event_id, attempts, url)
        meta = payload.get(CLIP_META_KEY) if isinstance(payload.get(CLIP_META_KEY), dict) else {}
        path = str((meta or {}).get("path") or "").strip()
        key = str((meta or {}).get("key") or "").strip()
        # Keep the local file when MinIO has no key — resend still needs it.
        if path and key:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                logger.warning("failed to remove local clip %s", path)
    elif final_status == "dead":
        log = logger.info if _non_retryable(last_error) else logger.error
        log(
            "webhook dead event=%s attempts=%s url=%s error=%s",
            event_id,
            attempts,
            url,
            last_error,
        )
    else:
        logger.warning(
            "webhook retry event=%s attempt=%s url=%s error=%s",
            event_id,
            attempts,
            url,
            last_error,
        )


class OutboundWorker:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="outbound-webhooks", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=5.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if db_enabled() and get_store().get_settings().enable_http_sink:
                    ids = _claim_jobs()
                    for job_id in ids:
                        try:
                            process_job(job_id)
                        except Exception:
                            logger.exception("outbound job failed id=%s", job_id)
            except SQLAlchemyError:
                logger.exception("outbound worker db error")
            except Exception:
                logger.exception("outbound worker failed")
            self._stop.wait(0.5)


_worker: OutboundWorker | None = None


def get_outbound_worker() -> OutboundWorker:
    global _worker
    if _worker is None:
        _worker = OutboundWorker()
    return _worker
