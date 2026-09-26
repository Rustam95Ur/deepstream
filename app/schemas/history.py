"""History / outbound / clip API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


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
