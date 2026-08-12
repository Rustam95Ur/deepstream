"""Build trigger payload (Campus-compatible contract)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


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
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event_id": event_id or str(uuid.uuid4()),
        "category": category,
        "camera_id": str(camera_id),
        "trigger_type": trigger_type,
        "trigger_time": datetime.now(timezone.utc).isoformat(),
        "pre_s": float(pre_s),
        "post_s": float(post_s),
        "evidence": evidence or {},
        "model_versions": {
            "detector": "yolo11n",
            "first_line": "nexus_deepstream",
        },
    }
    if node_id:
        payload["node_id"] = node_id
    if source_video:
        payload["source_video"] = source_video
    if source_offset_s is not None:
        payload["source_offset_s"] = float(source_offset_s)
    return payload
