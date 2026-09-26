"""Webhook registry CRUD and settings seed."""

from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy import func, select

from app.db import db_enabled, session_scope
from app.models import WebhookRow
from app.settings import NodeSettings
from app.storage import get_store
from app.timeutil import utcnow
from app.web.passwords import hash_password, verify_password
from app.webhooks.models import Webhook, from_row

logger = logging.getLogger(__name__)


def list_webhooks() -> list[Webhook]:
    if not db_enabled():
        return []
    with session_scope(write=False) as session:
        rows = session.scalars(
            select(WebhookRow).order_by(WebhookRow.created_at, WebhookRow.id)
        ).all()
        return [from_row(r) for r in rows]


def list_enabled_webhooks() -> list[Webhook]:
    return [w for w in list_webhooks() if w.enabled and w.url]


def get_webhook(webhook_id: str) -> Webhook | None:
    if not db_enabled():
        return None
    with session_scope(write=False) as session:
        row = session.get(WebhookRow, webhook_id)
        return from_row(row) if row else None


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
        return from_row(row)


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
    now = utcnow()
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
        return from_row(row)


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
        row.updated_at = utcnow()
        session.flush()
        return from_row(row)


def delete_webhook(webhook_id: str) -> bool:
    with session_scope(write=True) as session:
        row = session.get(WebhookRow, webhook_id)
        if row is None:
            return False
        session.delete(row)
        return True


def seed_webhooks_from_settings(settings: NodeSettings | None = None) -> None:
    """Create the first webhook from ``settings.triggers_url`` if the table is empty.

    After that, the webhooks table is the only outbound URL source.
    """
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
        now = utcnow()
        session.add(
            WebhookRow(
                id=str(uuid4()),
                name="default",
                url=url,
                enabled=True,
                timeout_sec=float(cfg.triggers_timeout_sec or 5.0),
                max_retries=5,
                created_at=now,
                updated_at=now,
            )
        )
        logger.info("seeded webhook from settings.triggers_url")
