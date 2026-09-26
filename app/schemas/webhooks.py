"""Webhook and camera-sync API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class WebhookIn(BaseModel):
    name: str = Field(default="", max_length=128)
    url: str = Field(..., min_length=8, max_length=2048)
    enabled: bool = True
    login: str = Field(default="", max_length=128)
    password: str | None = Field(default=None, max_length=128)
    timeout_sec: float = Field(default=5.0, ge=1.0, le=120.0)
    max_retries: int = Field(default=5, ge=0, le=20)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return (v or "").strip() or "webhook"

    @field_validator("login")
    @classmethod
    def _login(cls, v: str) -> str:
        login = (v or "").strip()
        if ":" in login:
            raise ValueError("логин не должен содержать :")
        return login

    @field_validator("password")
    @classmethod
    def _password(cls, v: str | None) -> str | None:
        if v is None:
            return None
        secret = v.strip()
        if not secret:
            return None
        if len(secret) < 8:
            raise ValueError("пароль минимум 8 символов")
        return secret

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        url = (v or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ValueError("URL должен начинаться с http:// или https://")
        return url


class WebhookOut(BaseModel):
    id: str
    name: str
    url: str
    enabled: bool
    login: str = ""
    auth_configured: bool = False
    timeout_sec: float = 5.0
    max_retries: int = 5
    created_at: datetime
    updated_at: datetime


class WebhookListOut(BaseModel):
    items: list[WebhookOut]


class CameraSyncWebhookResult(BaseModel):
    webhook_id: str
    webhook_name: str
    url: str
    ok: bool
    http_status: int | None = None
    created: int = 0
    updated: int = 0
    skipped: int = 0
    error: str = ""


class CameraSyncPushOut(BaseModel):
    ok: bool
    node_id: str
    cameras: int
    results: list[CameraSyncWebhookResult] = []
    error: str = ""
