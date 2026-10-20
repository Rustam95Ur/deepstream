"""Webhook and camera-sync API schemas."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator


class WebhookIn(BaseModel):
    name: str = Field(default="", max_length=128)
    url: str = Field(..., min_length=8, max_length=2048)
    enabled: bool = True
    login: str = Field(default="", max_length=128)
    password: str | None = Field(default=None, max_length=128)
    timeout_sec: float = Field(default=5.0, ge=1.0, le=120.0)
    max_retries: int = Field(default=5, ge=0, le=20)
    proxy_enabled: bool = False
    proxy_host: str = Field(default="", max_length=255)
    proxy_port: int = Field(default=0, ge=0, le=65535)
    proxy_login: str = Field(default="", max_length=128)
    proxy_password: str | None = Field(default=None, max_length=256)

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

    @field_validator("proxy_login")
    @classmethod
    def _proxy_login(cls, v: str) -> str:
        login = (v or "").strip()
        if ":" in login:
            raise ValueError("логин прокси не должен содержать :")
        return login

    @field_validator("proxy_password")
    @classmethod
    def _proxy_password(cls, v: str | None) -> str | None:
        if v is None:
            return None
        secret = v.strip()
        return secret or None

    @model_validator(mode="before")
    @classmethod
    def _split_proxy_endpoint(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        raw = str(data.get("proxy_host") or "").strip()
        if not raw:
            return data
        try:
            port_n = int(data.get("proxy_port") or 0)
        except (TypeError, ValueError):
            port_n = 0
        host, extracted = _parse_proxy_host(raw)
        out = dict(data)
        out["proxy_host"] = host
        if extracted and port_n <= 0:
            out["proxy_port"] = extracted
        return out

    @model_validator(mode="after")
    def _proxy_required(self) -> WebhookIn:
        if self.proxy_host and any(ch.isspace() for ch in self.proxy_host):
            raise ValueError("некорректный хост прокси")
        if self.proxy_password and not self.proxy_login:
            raise ValueError("укажите логин прокси")
        if not self.proxy_enabled:
            return self
        if not self.proxy_host:
            raise ValueError("укажите хост прокси")
        if not (1 <= int(self.proxy_port) <= 65535):
            raise ValueError("укажите порт прокси")
        return self


class WebhookOut(BaseModel):
    id: str
    name: str
    url: str
    enabled: bool
    login: str = ""
    auth_configured: bool = False
    timeout_sec: float = 5.0
    max_retries: int = 5
    proxy_enabled: bool = False
    proxy_host: str = ""
    proxy_port: int = 0
    proxy_login: str = ""
    proxy_auth_configured: bool = False
    created_at: datetime
    updated_at: datetime


def _parse_proxy_host(raw: str) -> tuple[str, int | None]:
    """Return ``(host, port)``. Port is set when it was part of the pasted value."""
    text = (raw or "").strip()
    if not text:
        return "", None
    if "://" in text:
        parsed = urlparse(text)
        return (parsed.hostname or "").strip(), parsed.port
    host = text.split("/")[0].strip()
    if host.startswith("[") and "]" in host:
        end = host.index("]")
        name = host[1:end].strip()
        rest = host[end + 1 :]
        if rest.startswith(":") and rest[1:].isdigit():
            return name, int(rest[1:])
        return name, None
    if host.count(":") == 1:
        name, port_text = host.rsplit(":", 1)
        if port_text.isdigit():
            return name.strip(), int(port_text)
    return host, None


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
