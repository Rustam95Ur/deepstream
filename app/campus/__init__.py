"""Campus contract: SmartBox ingest, clip URLs, camera id resolution."""

from __future__ import annotations

from app.campus.cameras import (
    CameraResolver,
    StoreCameraResolver,
    get_camera_resolver,
    resolve_camera_id,
    set_camera_resolver,
)
from app.campus.ingest import ALGO_MODEL, to_smartbox_ingest
from app.campus.urls import public_clip_url, refresh_video_url

__all__ = [
    "ALGO_MODEL",
    "CameraResolver",
    "StoreCameraResolver",
    "get_camera_resolver",
    "public_clip_url",
    "refresh_video_url",
    "resolve_camera_id",
    "set_camera_resolver",
    "to_smartbox_ingest",
]
