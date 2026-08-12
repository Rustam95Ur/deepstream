"""Pydantic API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class CameraIn(BaseModel):
    id: str = Field(..., min_length=1, max_length=128, description="Stable id on this node")
    name: str = Field(default="", max_length=255)
    main_uri: str = Field(..., min_length=1, description="rtsp:// or file://")
    enabled: bool = True
    external_id: str = Field(
        default="",
        max_length=128,
        description="Optional Django Camera.pk once synced",
    )
    meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("main_uri")
    @classmethod
    def _strip_uri(cls, v: str) -> str:
        return (v or "").strip()

    @field_validator("id", "name", "external_id")
    @classmethod
    def _strip_ids(cls, v: str) -> str:
        return (v or "").strip()


class CameraOut(CameraIn):
    created_at: datetime
    updated_at: datetime


class CameraListOut(BaseModel):
    node_id: str
    cameras: list[CameraOut]
    updated_at: datetime | None = None
    next_cursor: str | None = None


class HealthOut(BaseModel):
    status: str
    node_id: str
    node_name: str
    version: str
    cameras_count: int
    cameras_enabled: int
    pipeline_running: bool
    pipeline_available: bool
    pipeline_detail: str = ""
    triggers_url: str = ""
    cameras_url: str = ""


class WorkerStatusOut(BaseModel):
    running: bool
    available: bool
    detail: str = ""
    last_started_at: datetime | None = None
    last_error: str = ""
    camera_ids: list[str] = Field(default_factory=list)


class TriggerEventOut(BaseModel):
    event_id: str
    camera_id: str
    trigger_type: str
    category: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class TriggerHistoryOut(BaseModel):
    items: list[TriggerEventOut]
    next_cursor: str | None = None


class SendEventOut(BaseModel):
    event_id: str
    sink: str
    url: str = ""
    status: str
    http_status: int | None = None
    error: str = ""
    created_at: datetime


class SendHistoryOut(BaseModel):
    items: list[SendEventOut]
    next_cursor: str | None = None


def _normalize_email(value: str) -> str:
    email = (value or "").strip().lower()
    if len(email) > 255:
        raise ValueError("email слишком длинный")
    local, sep, domain = email.partition("@")
    if not sep or not local or not domain or " " in email:
        raise ValueError("Некорректный email")
    if "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise ValueError("Некорректный email")
    return email


class UserIn(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    name: str = Field(default="", max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _normalize_email(v)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return (v or "").strip()


class UserUpdateIn(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    name: str = Field(default="", max_length=128)
    password: str = Field(default="", max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _normalize_email(v)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return (v or "").strip()

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        raw = v or ""
        if raw and len(raw) < 8:
            raise ValueError("Пароль слишком короткий")
        return raw


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    created_at: datetime
    updated_at: datetime


class UserListOut(BaseModel):
    users: list[UserOut]
    next_cursor: str | None = None
    total: int = 0


class LoginIn(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=128)
    password_confirm: str = ""

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return _normalize_email(v)


class SessionOut(BaseModel):
    authenticated: bool
    setup: bool
    user_id: str = ""
    email: str = ""
    name: str = ""
    node_id: str
    node_name: str
