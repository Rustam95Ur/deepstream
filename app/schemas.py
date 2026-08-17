"""Pydantic API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from app.trigger_types import camera_trigger_override

_CAMERA_KNOWN = {
    "id",
    "camera_id",
    "channel_id",
    "name",
    "title",
    "channel_name",
    "main_uri",
    "uri",
    "rtsp_url",
    "url",
    "enabled",
    "external_id",
    "meta",
    "enabled_triggers",
    "created_at",
    "updated_at",
}


def _first_str(*values: object) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _as_bool(value: object, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


class CameraIn(BaseModel):
    """Inbound camera. Accepts Campus/SmartBox aliases: camera_id, rtsp_url, uri."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str = Field(default="", max_length=128, description="Stable id on this node")
    name: str = Field(default="", max_length=255)
    main_uri: str = Field(..., min_length=1, description="rtsp:// or file://")
    enabled: bool = True
    external_id: str = Field(
        default="",
        max_length=128,
        description="Optional Django Camera.pk once synced",
    )
    meta: dict[str, Any] = Field(default_factory=dict)
    enabled_triggers: list[str] | None = Field(
        default=None,
        description="None = inherit node settings. Empty list = none on this camera.",
    )

    @model_validator(mode="before")
    @classmethod
    def _aliases(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        raw = dict(data)
        cam_id = _first_str(
            raw.get("id"),
            raw.get("camera_id"),
            raw.get("channel_id"),
            raw.get("external_id"),
        )
        uri = _first_str(raw.get("main_uri"), raw.get("uri"), raw.get("rtsp_url"), raw.get("url"))
        name = _first_str(raw.get("name"), raw.get("title"), raw.get("channel_name"), cam_id)
        extra_meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
        leftover = {k: v for k, v in raw.items() if k not in _CAMERA_KNOWN}
        raw["id"] = cam_id
        raw["name"] = name
        raw["main_uri"] = uri
        raw["enabled"] = _as_bool(raw.get("enabled"), True)
        raw["external_id"] = _first_str(raw.get("external_id"))
        raw["meta"] = {**leftover, **extra_meta}
        if "enabled_triggers" not in raw:
            raw["enabled_triggers"] = None
        return raw

    @field_validator("id", "name", "external_id", "main_uri", mode="before")
    @classmethod
    def _strip_text(cls, v: object) -> str:
        if v is None:
            return ""
        return str(v).strip()

    @field_validator("enabled_triggers", mode="before")
    @classmethod
    def _triggers(cls, v: object) -> list[str] | None:
        return camera_trigger_override(v)


class CameraPatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    name: str | None = None
    main_uri: str | None = None
    enabled: bool | None = None
    external_id: str | None = None
    meta: dict[str, Any] | None = None
    enabled_triggers: list[str] | None = None

    @model_validator(mode="before")
    @classmethod
    def _aliases(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        raw = dict(data)
        if "main_uri" not in raw:
            uri = _first_str(raw.get("uri"), raw.get("rtsp_url"), raw.get("url"))
            if uri:
                raw["main_uri"] = uri
        if "name" not in raw:
            name = _first_str(raw.get("title"), raw.get("channel_name"))
            if name:
                raw["name"] = name
        if "enabled" in raw:
            raw["enabled"] = _as_bool(raw.get("enabled"), True)
        return raw

    @field_validator("name", "external_id", "main_uri")
    @classmethod
    def _strip_opt(cls, v: str | None) -> str | None:
        if v is None:
            return None
        text = v.strip()
        if not text:
            raise ValueError("пустое значение")
        return text

    @field_validator("enabled_triggers", mode="before")
    @classmethod
    def _triggers(cls, v: object) -> list[str] | None:
        if v is None:
            return None
        return camera_trigger_override(v)


class CameraOut(CameraIn):
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def uri(self) -> str:
        return self.main_uri

    @computed_field
    @property
    def rtsp_url(self) -> str:
        return self.main_uri


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


class CameraSkipOut(BaseModel):
    camera_id: str
    name: str = ""
    reason: str


class LogLineOut(BaseModel):
    ts: datetime | None = None
    level: str = "WARNING"
    logger: str = ""
    message: str = ""


class WorkerStatusOut(BaseModel):
    running: bool
    available: bool
    detail: str = ""
    last_started_at: datetime | None = None
    last_error: str = ""
    camera_ids: list[str] = Field(default_factory=list)
    reload_pending: bool = False
    max_streams: int = 0
    skipped: list[CameraSkipOut] = Field(default_factory=list)
    recent_errors: list[LogLineOut] = Field(default_factory=list)


class RingCameraHealthOut(BaseModel):
    camera_id: str
    name: str
    alive: bool
    stalled: bool = False
    last_segment_age_s: float | None = None
    restarts: int = 0
    codec: str = ""
    last_error: str = ""


class VideoHealthOut(BaseModel):
    status: str
    gst_available: bool = False
    clip_record: bool = False
    ring_running: bool = False
    pipeline: WorkerStatusOut
    cameras: list[RingCameraHealthOut] = Field(default_factory=list)
    recent_errors: list[LogLineOut] = Field(default_factory=list)


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


class OutboundJobOut(BaseModel):
    id: str
    event_id: str
    webhook_id: str
    url: str
    attempts: int
    max_attempts: int
    status: str
    last_error: str = ""
    http_status: int | None = None
    next_attempt_at: datetime
    created_at: datetime
    updated_at: datetime


class OutboundJobListOut(BaseModel):
    items: list[OutboundJobOut]
    next_cursor: str | None = None


class ResendOut(BaseModel):
    event_id: str
    queued: int


class ClipUrlOut(BaseModel):
    event_id: str
    url: str = ""
    bucket: str = ""
    key: str = ""


class ClipOut(BaseModel):
    url: str = ""
    bucket: str = ""
    key: str = ""


class TriggerEventOut(BaseModel):
    event_id: str
    camera_id: str
    camera_name: str = ""
    trigger_type: str
    category: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    clip: ClipOut = Field(default_factory=ClipOut)
    video_url: str = ""
    video_bucket: str = ""
    video_key: str = ""
    created_at: datetime


class TriggerEventDetailOut(TriggerEventOut):
    payload: dict[str, Any] = Field(default_factory=dict)


class TriggerHistoryOut(BaseModel):
    items: list[TriggerEventOut]
    next_cursor: str | None = None


class SendEventOut(BaseModel):
    id: str = ""
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
