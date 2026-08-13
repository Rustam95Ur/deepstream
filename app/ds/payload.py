"""Stable trigger payload: event_id, clip, video_url are always present."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


def _str(value: Any) -> str:
    return str(value or "").strip()


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clip_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    raw = payload.get("clip") if isinstance(payload.get("clip"), dict) else {}
    url = _str(payload.get("video_url") or raw.get("url"))
    bucket = _str(payload.get("video_bucket") or raw.get("bucket"))
    key = _str(payload.get("video_key") or raw.get("key"))
    return {"url": url, "bucket": bucket, "key": key}


def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Always emit the public contract, including empty clip / video_url."""
    clip = clip_from_payload(payload)
    evidence = payload.get("evidence")
    models = payload.get("model_versions")
    out: dict[str, Any] = {
        "event_id": _str(payload.get("event_id")),
        "category": _str(payload.get("category")) or "incident",
        "camera_id": _str(payload.get("camera_id")),
        "camera_name": _str(payload.get("camera_name")),
        "trigger_type": _str(payload.get("trigger_type")),
        "trigger_time": _str(payload.get("trigger_time")),
        "pre_s": _float(payload.get("pre_s")),
        "post_s": _float(payload.get("post_s")),
        "evidence": evidence if isinstance(evidence, dict) else {},
        "model_versions": models
        if isinstance(models, dict)
        else {"detector": "yolo11n", "first_line": "nexus_deepstream"},
        "clip": clip,
        "video_url": clip["url"],
        "video_bucket": clip["bucket"],
        "video_key": clip["key"],
    }
    node_id = _str(payload.get("node_id"))
    if node_id:
        out["node_id"] = node_id
    source_video = _str(payload.get("source_video"))
    if source_video:
        out["source_video"] = source_video
    if payload.get("source_offset_s") is not None:
        out["source_offset_s"] = _float(payload.get("source_offset_s"))
    return out


def attach_clip(
    payload: dict[str, Any],
    *,
    url: str = "",
    bucket: str = "",
    key: str = "",
) -> dict[str, Any]:
    payload["video_url"] = _str(url)
    payload["video_bucket"] = _str(bucket)
    payload["video_key"] = _str(key)
    payload["clip"] = {
        "url": payload["video_url"],
        "bucket": payload["video_bucket"],
        "key": payload["video_key"],
    }
    return payload


def build_payload(
    *,
    camera_id: str,
    trigger_type: str,
    pre_s: float,
    post_s: float,
    evidence: dict[str, Any] | None = None,
    event_id: str | None = None,
    category: str = "incident",
    source_video: str | None = None,
    source_offset_s: float | None = None,
    node_id: str = "",
    camera_name: str = "",
    video_url: str | None = None,
    video_key: str | None = None,
    video_bucket: str | None = None,
) -> dict[str, Any]:
    return normalize_payload(
        {
            "event_id": event_id or str(uuid.uuid4()),
            "category": category,
            "camera_id": str(camera_id),
            "camera_name": camera_name or str(camera_id),
            "trigger_type": trigger_type,
            "trigger_time": datetime.now(timezone.utc).isoformat(),
            "pre_s": float(pre_s),
            "post_s": float(post_s),
            "evidence": evidence or {},
            "model_versions": {
                "detector": "yolo11n",
                "first_line": "nexus_deepstream",
            },
            "node_id": node_id,
            "source_video": source_video,
            "source_offset_s": source_offset_s,
            "video_url": video_url or "",
            "video_key": video_key or "",
            "video_bucket": video_bucket or "",
        }
    )
