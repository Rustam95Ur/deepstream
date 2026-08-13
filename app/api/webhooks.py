"""Webhook CRUD."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api import ApiAuth
from app.db import db_enabled
from app.schemas import WebhookIn, WebhookListOut, WebhookOut
from app.webhooks import (
    LoginTakenError,
    Webhook,
    create_webhook,
    delete_webhook,
    get_webhook,
    list_webhooks,
    update_webhook,
)

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"], dependencies=[ApiAuth])


def _require_db() -> None:
    if not db_enabled():
        raise HTTPException(status_code=503, detail="Postgres is not configured")


def _out(hook: Webhook) -> WebhookOut:
    return WebhookOut(
        id=hook.id,
        name=hook.name,
        url=hook.url,
        enabled=hook.enabled,
        login=hook.login,
        auth_configured=hook.auth_configured,
        timeout_sec=hook.timeout_sec,
        max_retries=hook.max_retries,
        created_at=hook.created_at,
        updated_at=hook.updated_at,
    )


@router.get("", response_model=WebhookListOut)
def get_webhooks() -> WebhookListOut:
    _require_db()
    return WebhookListOut(items=[_out(w) for w in list_webhooks()])


@router.post("", response_model=WebhookOut, status_code=status.HTTP_201_CREATED)
def post_webhook(body: WebhookIn) -> WebhookOut:
    _require_db()
    if not body.login:
        raise HTTPException(status_code=400, detail="Укажите логин для входящего API")
    if not body.password:
        raise HTTPException(status_code=400, detail="Укажите пароль для входящего API")
    try:
        hook = create_webhook(
            name=body.name,
            url=body.url,
            enabled=body.enabled,
            login=body.login,
            password=body.password,
            timeout_sec=body.timeout_sec,
            max_retries=body.max_retries,
        )
    except LoginTakenError:
        raise HTTPException(status_code=409, detail="Этот логин уже занят") from None
    return _out(hook)


@router.put("/{webhook_id}", response_model=WebhookOut)
def put_webhook(webhook_id: str, body: WebhookIn) -> WebhookOut:
    _require_db()
    existing = get_webhook(webhook_id)
    if existing and (body.login or existing.login) and not existing.auth_configured and not body.password:
        raise HTTPException(status_code=400, detail="Укажите пароль для входящего API")
    try:
        hook = update_webhook(
            webhook_id,
            name=body.name,
            url=body.url,
            enabled=body.enabled,
            timeout_sec=body.timeout_sec,
            max_retries=body.max_retries,
            login=body.login or None,
            password=body.password,
        )
    except LoginTakenError:
        raise HTTPException(status_code=409, detail="Этот логин уже занят") from None
    if hook is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return _out(hook)


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_webhook(webhook_id: str) -> None:
    _require_db()
    if not delete_webhook(webhook_id):
        raise HTTPException(status_code=404, detail="Webhook not found")
