"""Webhook registry, HMAC signing, outbound retry queue."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.db import db_enabled, session_scope
from app.ds.payload import normalize_payload
from app.ds.sinks.http_sink import post_json
from app.history import record_send
from app.models import OutboundJobRow, TriggerEventRow, WebhookRow
from app.settings import NodeSettings
from app.storage import get_store

logger = logging.getLogger(__name__)

OPEN_STATUSES = ("pending", "retrying")
MAX_BACKOFF_S = 60.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sign_body(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.".encode("utf-8") + body,
        hashlib.sha256,
    )
    return mac.hexdigest()


def signature_headers(*, secret: str, event_id: str, body: bytes) -> dict[str, str]:
    if not (secret or "").strip():
        return {}
    timestamp = str(int(time.time()))
    digest = sign_body(secret.strip(), timestamp, body)
    return {
        "X-Nexus-Signature": f"sha256={digest}",
        "X-Nexus-Timestamp": timestamp,
        "X-Nexus-Event-Id": event_id,
    }


@dataclass(frozen=True, slots=True)
class Webhook:
    id: str
    name: str
    url: str
    enabled: bool
    hmac_secret: str
    timeout_sec: float
    max_retries: int
    created_at: datetime
    updated_at: datetime

    @property
    def hmac_configured(self) -> bool:
        return bool(self.hmac_secret.strip())

    @property
    def max_attempts(self) -> int:
        return max(1, int(self.max_retries) + 1)


def _from_row(row: WebhookRow) -> Webhook:
    return Webhook(
        id=row.id,
        name=row.name or "",
        url=(row.url or "").strip(),
        enabled=bool(row.enabled),
        hmac_secret=row.hmac_secret or "",
        timeout_sec=float(row.timeout_sec or 5.0),
        max_retries=int(row.max_retries or 0),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def list_webhooks() -> list[Webhook]:
    if not db_enabled():
        return []
    with session_scope(write=False) as session:
        rows = session.scalars(select(WebhookRow).order_by(WebhookRow.created_at, WebhookRow.id)).all()
        return [_from_row(r) for r in rows]


def list_enabled_webhooks() -> list[Webhook]:
    return [w for w in list_webhooks() if w.enabled and w.url]


def get_webhook(webhook_id: str) -> Webhook | None:
    if not db_enabled():
        return None
    with session_scope(write=False) as session:
        row = session.get(WebhookRow, webhook_id)
        return _from_row(row) if row else None


def create_webhook(
    *,
    name: str,
    url: str,
    enabled: bool = True,
    hmac_secret: str = "",
    timeout_sec: float = 5.0,
    max_retries: int = 5,
) -> Webhook:
    now = _utcnow()
    row = WebhookRow(
        id=str(uuid4()),
        name=(name or "").strip() or "webhook",
        url=(url or "").strip(),
        enabled=bool(enabled),
        hmac_secret=(hmac_secret or "").strip(),
        timeout_sec=float(timeout_sec),
        max_retries=int(max_retries),
        created_at=now,
        updated_at=now,
    )
    with session_scope(write=True) as session:
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
    hmac_secret: str | None = None,
) -> Webhook | None:
    with session_scope(write=True) as session:
        row = session.get(WebhookRow, webhook_id)
        if row is None:
            return None
        row.name = (name or "").strip() or row.name
        row.url = (url or "").strip()
        row.enabled = bool(enabled)
        row.timeout_sec = float(timeout_sec)
        row.max_retries = int(max_retries)
        if hmac_secret is not None:
            row.hmac_secret = hmac_secret.strip()
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
                    payload=body,
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
        row = session.scalar(select(TriggerEventRow).where(TriggerEventRow.event_id == eid))
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


def _deliver(job: OutboundJobRow) -> tuple[bool, int | None, str]:
    hook: Webhook | None = None
    with session_scope(write=False) as session:
        row = session.get(WebhookRow, job.webhook_id)
        if row is not None:
            hook = _from_row(row)
    if hook is not None and not hook.enabled:
        return False, None, "webhook disabled"
    url = (hook.url if hook else job.url) or job.url
    secret = hook.hmac_secret if hook else ""
    timeout = hook.timeout_sec if hook else 5.0
    body = json.dumps(job.payload or {}, ensure_ascii=False).encode("utf-8")
    event_id = str(job.event_id or "")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "nexus-deepstream/0.1",
        **signature_headers(secret=secret, event_id=event_id, body=body),
    }
    return post_json(url, body, headers=headers, timeout_sec=timeout)


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
        claim_at = now + timedelta(seconds=30)
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
            if row.attempts >= max(1, int(row.max_attempts or 1)):
                row.status = "dead"
                row.next_attempt_at = now
            else:
                row.status = "retrying"
                row.next_attempt_at = now + timedelta(seconds=_backoff_s(row.attempts))
        event_id = row.event_id
        url = row.url
        status = "ok" if ok else "error"
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
    elif final_status == "dead":
        logger.error(
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
        self._thread = threading.Thread(target=self._loop, name="outbound-webhooks", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=5.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if db_enabled():
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
