"""Node health, billing, and video worker schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


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
    license_valid: bool = False
    license_reason: str = ""


class BillingCheckOut(BaseModel):
    url: str
    motherboard_serial: str = ""
    api_key_configured: bool = False
    valid: bool = False
    reason: str = ""
    destroy: bool = False
    client_name: str = ""
    module: str = ""
    checked_at: datetime | None = None


class BillingValidateIn(BaseModel):
    billing_url: str | None = None
    billing_api_key: str | None = None


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
