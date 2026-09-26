"""Camera API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from app.schemas._util import as_bool, first_str
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
    "is_active",
    "external_id",
    "meta",
    "enabled_triggers",
    "created_at",
    "updated_at",
}


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
        description="Optional Camera.pk once synced",
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
        cam_id = first_str(
            raw.get("id"),
            raw.get("camera_id"),
            raw.get("channel_id"),
            raw.get("external_id"),
        )
        uri = first_str(
            raw.get("main_uri"), raw.get("uri"), raw.get("rtsp_url"), raw.get("url")
        )
        name = first_str(
            raw.get("name"), raw.get("title"), raw.get("channel_name"), cam_id
        )
        extra_meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
        leftover = {k: v for k, v in raw.items() if k not in _CAMERA_KNOWN}
        if "enabled" not in raw and "is_active" in raw:
            raw["enabled"] = raw.get("is_active")
        raw["id"] = cam_id
        raw["name"] = name
        raw["main_uri"] = uri
        raw["enabled"] = as_bool(raw.get("enabled"), True)
        raw["external_id"] = first_str(raw.get("external_id"))
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
            uri = first_str(raw.get("uri"), raw.get("rtsp_url"), raw.get("url"))
            if uri:
                raw["main_uri"] = uri
        if "name" not in raw:
            name = first_str(raw.get("title"), raw.get("channel_name"))
            if name:
                raw["name"] = name
        leftover = {k: v for k, v in raw.items() if k not in _CAMERA_KNOWN}
        extra_meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
        if leftover or extra_meta:
            raw["meta"] = {**leftover, **extra_meta}
        if "enabled" not in raw and "is_active" in raw:
            raw["enabled"] = raw.get("is_active")
        if "enabled" in raw:
            raw["enabled"] = as_bool(raw.get("enabled"), True)
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


class CameraTestBatchIn(BaseModel):
    """Create N enabled cameras that share one RTSP/file URI."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    count: int = Field(..., ge=1, le=128, description="How many test cameras to create")
    main_uri: str = Field(
        ..., min_length=1, description="rtsp:// or file:// used by every camera"
    )

    @model_validator(mode="before")
    @classmethod
    def _aliases(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        raw = dict(data)
        uri = first_str(
            raw.get("main_uri"), raw.get("uri"), raw.get("rtsp_url"), raw.get("url")
        )
        if uri:
            raw["main_uri"] = uri
        return raw

    @field_validator("main_uri", mode="before")
    @classmethod
    def _strip_uri(cls, v: object) -> str:
        return str(v).strip() if v is not None else ""


class CameraTestBatchOut(BaseModel):
    cameras: list[CameraOut]
    created: int
