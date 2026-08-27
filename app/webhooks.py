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
from app.ds.payload import clip_from_payload, normalize_payload, to_smartbox_ingest
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
VIDEO_POST_TIMEOUT_S = 60.0


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


def _clip_meta(payload: dict[str, Any]) -> dict[str, str]:
    raw = payload.get(CLIP_META_KEY)
    if isinstance(raw, dict):
        return {k: str(v or "").strip() for k, v in raw.items() if str(v or "").strip()}
    clip = clip_from_payload(payload)
    return {k: v for k, v in clip.items() if v}


def _split_outbound(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    raw = dict(payload or {})
    clip_meta = _clip_meta(raw)
    raw.pop(CLIP_META_KEY, None)
    outbound = to_smartbox_ingest(raw)
    outbound.pop(CLIP_META_KEY, None)
    return outbound, clip_meta


def _read_clip_bytes(clip_meta: dict[str, str]) -> bytes | None:
    path = (clip_meta.get("path") or "").strip()
    if path:
        file_path = Path(path)
        if file_path.is_file():
            try:
                return file_path.read_bytes()
            except OSError:
                logger.exception("failed to read clip %s", file_path)
    key = (clip_meta.get("key") or "").strip()
    if key:
        from app.minio_store import get_minio_store

        data = get_minio_store().get_object_bytes(key)
        if data:
            return data
    return None


def _cleanup_local_clip(clip_meta: dict[str, str]) -> None:
    path = (clip_meta.get("path") or "").strip()
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        logger.warning("failed to remove local clip %s", path)


def enqueue_payload(payload: dict[str, Any], *, reason: str = "trigger") -> int:
    body = normalize_payload(payload)
    event_id = str(body.get("event_id") or "")
    if requires_video(body) and not has_clip_source(body):
        record_send(
            event_id=event_id,
            sink="webhook",
            url="",
            status="skipped",
            error="video required",
        )
        logger.warning("skip webhook enqueue event=%s reason=%s: video required", event_id, reason)
        return 0
    outbound = to_smartbox_ingest(body)
    clip = clip_from_payload(body)
    if clip.get("key"):
        # Kept for multipart delivery; Campus ignores unknown top-level keys.
        outbound["_nexus_clip"] = {
            "key": clip["key"],
            "bucket": clip.get("bucket") or "",
        }
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
) -> tuple[bytes, str] | None:
    """Load incident MP4 from MinIO for webhook multipart delivery."""
    raw = payload if isinstance(payload, dict) else {}
    nested = raw.get("_nexus_clip") if isinstance(raw.get("_nexus_clip"), dict) else {}
    key = str(nested.get("key") or "").strip()
    if not key:
        clip = clip_from_payload(raw)
        key = clip.get("key") or ""
    eid = (event_id or "").strip()
    if not key and eid and db_enabled():
        with session_scope(write=False) as session:
            row = session.scalar(
                select(TriggerEventRow).where(TriggerEventRow.event_id == eid)
            )
            hist = dict(row.payload or {}) if row else {}
        key = clip_from_payload(hist).get("key") or ""
    if not key:
        return None
    data = get_minio_store().get_object_bytes(key)
    if not data:
        return None
    safe = "".join(
        ch if ch.isalnum() or ch in "-_." else "_" for ch in (eid or "clip")
    )[:80]
    return data, f"{safe or 'clip'}.mp4"


def _deliver(job: OutboundJobRow) -> tuple[bool, int | None, str]:
    hook: Webhook | None = None
    with session_scope(write=False) as session:
        row = session.get(WebhookRow, job.webhook_id)
        if row is not None:
            hook = _from_row(row)
    if hook is not None and not hook.enabled:
        return False, None, "webhook disabled"
    url = (hook.url if hook else job.url) or job.url
    timeout = hook.timeout_sec if hook else 5.0
    outbound = to_smartbox_ingest(job.payload or {})
    outbound.pop("_nexus_clip", None)
    event_id = str(job.event_id or "")
    headers = {
        "User-Agent": "nexus-deepstream/0.1",
    }
    if event_id:
        headers["X-Nexus-Event-Id"] = event_id

    clip = _clip_bytes_for_event(
        event_id, job.payload if isinstance(job.payload, dict) else None
    )
    if clip is not None:
        video_bytes, filename = clip
        # Uploading MP4 needs more time than a JSON ACK.
        send_timeout = max(float(timeout), 120.0)
        return post_multipart(
            url,
            fields={"payload": json.dumps(outbound, ensure_ascii=False)},
            files={"video": (filename, video_bytes, "video/mp4")},
            headers=headers,
            timeout_sec=send_timeout,
        )

    body = json.dumps(outbound, ensure_ascii=False).encode("utf-8")
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
        _cleanup_local_clip(_clip_meta(payload))
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
