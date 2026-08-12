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
