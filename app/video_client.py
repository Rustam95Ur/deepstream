"""HTTP client from the API container to the video container (pipeline + ring-buffer)."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from app.pipeline_status import as_log_lines
from app.schemas import (
    CameraSkipOut,
    LogLineOut,
    RingCameraHealthOut,
    VideoHealthOut,
    WorkerStatusOut,
)

logger = logging.getLogger(__name__)


def video_base_url() -> str:
    return (os.environ.get("NEXUS_DS_VIDEO_URL") or "").strip().rstrip("/")


def video_token() -> str:
    return (os.environ.get("NEXUS_DS_VIDEO_TOKEN") or "").strip()


def video_configured() -> bool:
    return bool(video_base_url())


def _offline(detail: str) -> WorkerStatusOut:
    return WorkerStatusOut(
        running=False,
        available=False,
        detail=detail,
        last_started_at=None,
        last_error=detail,
        camera_ids=[],
        recent_errors=[LogLineOut(level="ERROR", logger="video", message=detail)],
    )


def _offline_health(detail: str) -> VideoHealthOut:
    pipe = _offline(detail)
    return VideoHealthOut(
        status="error",
        gst_available=False,
        clip_record=False,
        ring_running=False,
        pipeline=pipe,
        cameras=[],
        recent_errors=list(pipe.recent_errors),
    )


def _parse_skips(raw: object) -> list[CameraSkipOut]:
    out: list[CameraSkipOut] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        cam_id = str(item.get("camera_id") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if not cam_id or not reason:
            continue
        out.append(
            CameraSkipOut(
                camera_id=cam_id,
                name=str(item.get("name") or cam_id),
                reason=reason,
            )
        )
    return out


def _parse_status(raw: dict[str, Any]) -> WorkerStatusOut:
    started = raw.get("last_started_at")
    last_started: datetime | None = None
    if started:
        try:
            last_started = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
        except ValueError:
            last_started = None
    ids = raw.get("camera_ids") or []
    if not isinstance(ids, list):
        ids = []
    return WorkerStatusOut(
        running=bool(raw.get("running")),
        available=bool(raw.get("available")),
        detail=str(raw.get("detail") or ""),
        last_started_at=last_started,
        last_error=str(raw.get("last_error") or ""),
        camera_ids=[str(x) for x in ids],
        reload_pending=bool(raw.get("reload_pending")),
        max_streams=int(raw.get("max_streams") or 0),
        skipped=_parse_skips(raw.get("skipped")),
        recent_errors=as_log_lines(list(raw.get("recent_errors") or [])),
    )


def _parse_health(raw: dict[str, Any]) -> VideoHealthOut:
    pipe = raw.get("pipeline") if isinstance(raw.get("pipeline"), dict) else {}
    cameras: list[RingCameraHealthOut] = []
    for item in raw.get("cameras") or []:
        if not isinstance(item, dict):
            continue
        cameras.append(
            RingCameraHealthOut(
                camera_id=str(item.get("camera_id") or ""),
                name=str(item.get("name") or ""),
                alive=bool(item.get("alive")),
                stalled=bool(item.get("stalled")),
                last_segment_age_s=item.get("last_segment_age_s"),
                restarts=int(item.get("restarts") or 0),
                codec=str(item.get("codec") or ""),
                last_error=str(item.get("last_error") or ""),
            )
        )
    errors = as_log_lines(list(raw.get("recent_errors") or []))
    status = _parse_status(pipe)
    if not errors:
        errors = list(status.recent_errors)
    return VideoHealthOut(
        status=str(raw.get("status") or "ok"),
        gst_available=bool(raw.get("gst_available")),
        clip_record=bool(raw.get("clip_record")),
        ring_running=bool(raw.get("ring_running")),
        pipeline=status,
        cameras=cameras,
        recent_errors=errors,
    )


def _request(method: str, path: str, *, timeout: float = 8.0) -> dict[str, Any]:
    base = video_base_url()
    if not base:
        raise RuntimeError("NEXUS_DS_VIDEO_URL is not set")
    headers = {
        "Accept": "application/json",
        "User-Agent": "nexus-deepstream-api/0.1",
    }
    token = video_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"{base}{path}",
        method=method,
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    if not body:
        return {}
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("video response must be a JSON object")
    return data


def worker_status() -> WorkerStatusOut:
    if not video_configured():
        return _offline("video container is not configured")
    try:
        return _parse_status(_request("GET", "/worker"))
    except Exception as exc:
        logger.warning("video status failed: %s", exc)
        return _offline(f"video container unreachable: {exc}")


def worker_start() -> WorkerStatusOut:
    if not video_configured():
        return _offline("video container is not configured")
    try:
        return _parse_status(_request("POST", "/worker/start"))
    except Exception as exc:
        logger.warning("video start failed: %s", exc)
        return _offline(f"video start failed: {exc}")


def worker_stop() -> WorkerStatusOut:
    if not video_configured():
        return _offline("video container is not configured")
    try:
        return _parse_status(_request("POST", "/worker/stop"))
    except Exception as exc:
        logger.warning("video stop failed: %s", exc)
        return _offline(f"video stop failed: {exc}")


def notify_reload() -> WorkerStatusOut | None:
    """Tell the video process to reload cameras/settings. Best-effort."""
    if not video_configured():
        return None
    try:
        return _parse_status(_request("POST", "/worker/reload"))
    except Exception as exc:
        logger.warning("video reload failed: %s", exc)
        return None


def video_health() -> VideoHealthOut:
    if not video_configured():
        return _offline_health("video container is not configured")
    try:
        return _parse_health(_request("GET", "/video/health"))
    except Exception as exc:
        logger.warning("video health failed: %s", exc)
        return _offline_health(f"video container unreachable: {exc}")
