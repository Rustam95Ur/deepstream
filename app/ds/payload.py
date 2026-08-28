"""Internal trigger payload + SmartBox ingest envelope for Campus."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit


def _str(value: Any) -> str:
    return str(value or "").strip()


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# Campus types (incident_type). Unknown trigger names are sent as-is.
_ALGO_MODEL = {
    "vif": "Драки",
    "convergence": "Драки",
    "fall": "Падение",
    "smoke": "Курение",
}

_DEFAULT_RTSP_PORTS = {554, 80, 443}


def ipc_addr_from_uri(uri: str) -> str:
    """Host (+ non-default port) + path, no credentials — Campus ``rtsp_url__icontains``."""
    raw = _str(uri)
    if not raw:
        return ""
    parsed = urlsplit(raw)
    host = (parsed.hostname or "").strip()
    path = (parsed.path or "").rstrip("/")
    if path == "/":
        path = ""
    if host:
        port = parsed.port
        hostport = host
        if port and port not in _DEFAULT_RTSP_PORTS:
            hostport = f"{host}:{port}"
        return f"{hostport}{path}" if path else hostport
    if "://" in raw:
        return ""
    if "@" in raw:
        raw = raw.rsplit("@", 1)[-1]
    return raw


_SKIP_VIDEO_TRIGGERS = frozenset({"", "stream_silent"})
CLIP_META_KEY = "_nexus_clip"


def clip_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    raw = payload.get("clip") if isinstance(payload.get("clip"), dict) else {}
    extra = (
        payload.get(CLIP_META_KEY)
        if isinstance(payload.get(CLIP_META_KEY), dict)
        else {}
    )
    url = _str(payload.get("video_url") or raw.get("url") or extra.get("url"))
    bucket = _str(
        payload.get("video_bucket") or raw.get("bucket") or extra.get("bucket")
    )
    key = _str(payload.get("video_key") or raw.get("key") or extra.get("key"))
    path = _str(payload.get("clip_path") or raw.get("path") or extra.get("path"))
    return {"url": url, "bucket": bucket, "key": key, "path": path}


def requires_video(payload: dict[str, Any]) -> bool:
    """Incident alerts must carry an MP4. ``stream_silent`` / errors do not."""
    if _str(payload.get("category")) == "error":
        return False
    alert = payload.get("alert_info")
    if isinstance(alert, dict):
        behaviour = (
            alert.get("behaviour") if isinstance(alert.get("behaviour"), dict) else {}
        )
        return bool(_str(behaviour.get("algo_model"))) or alert.get("type") in {1, "1"}
    return _str(payload.get("trigger_type")) not in _SKIP_VIDEO_TRIGGERS


def has_clip_source(payload: dict[str, Any]) -> bool:
    clip = clip_from_payload(payload)
    return bool(clip["key"] or clip["path"])


def missing_video_reason(payload: dict[str, Any]) -> str:
    """Why an incident webhook cannot include an MP4. Empty if video is not required."""
    if not requires_video(payload):
        return ""
    clip = clip_from_payload(payload)
    if clip["key"] or clip["path"]:
        return ""
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
    err = _str(evidence.get("webhook_video_error") or evidence.get("clip_error"))
    if err:
        return err
    trigger = _str(payload.get("trigger_type"))
    if trigger:
        return f"no clip for trigger={trigger}"
    return "no clip key and no local file"


def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Always emit the internal contract, including empty clip / video_url."""
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
        "model_versions": (
            models
            if isinstance(models, dict)
            else {"detector": "yolo11n", "first_line": "nexus_deepstream"}
        ),
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
    camera_uri = _str(
        payload.get("camera_uri") or payload.get("main_uri") or payload.get("rtsp_url")
    )
    if camera_uri:
        out["camera_uri"] = camera_uri
    ipc = _str(payload.get("ipc_addr")) or ipc_addr_from_uri(camera_uri)
    if ipc:
        out["ipc_addr"] = ipc
    return out


def attach_clip(
    payload: dict[str, Any],
    *,
    url: str = "",
    bucket: str = "",
    key: str = "",
    path: str = "",
) -> dict[str, Any]:
    payload["video_url"] = _str(url)
    payload["video_bucket"] = _str(bucket)
    payload["video_key"] = _str(key)
    payload["clip_path"] = _str(path)
    payload["clip"] = {
        "url": payload["video_url"],
        "bucket": payload["video_bucket"],
        "key": payload["video_key"],
        "path": payload["clip_path"],
    }
    return payload


def _capture_unix(trigger_time: str) -> int:
    raw = _str(trigger_time)
    if not raw:
        return int(datetime.now(timezone.utc).timestamp())
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except ValueError:
        return int(datetime.now(timezone.utc).timestamp())


def _time_received(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")


def _refresh_campus_video_url(event_id: str, video_url: str, *, has_clip: bool) -> str:
    eid = _str(event_id)
    url = _str(video_url)
    if not eid or not (url or has_clip):
        return url
    from app.minio_store import campus_clip_url

    return campus_clip_url(eid) or url


def to_smartbox_ingest(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Campus ``POST /api/v1/school/incident-ingest/`` body.

    Same shape as a SmartBox alert: envelope + ``alert_info`` with
    ``channel_info`` / ``behaviour.algo_model`` / ``behaviour.video_url``.
    Already-wrapped payloads are returned unchanged except ``video_url``,
    which is always rewritten to a Campus-reachable clip URL.
    """
    if isinstance(payload.get("alert_info"), dict):
        out = dict(payload)
        out.pop(CLIP_META_KEY, None)
        alert = dict(payload["alert_info"] or {})
        behaviour = dict(alert.get("behaviour") or {})
        channel = dict(alert.get("channel_info") or {})
        clip = clip_from_payload(payload)
        video_url = _refresh_campus_video_url(
            _str(payload.get("event_id")),
            _str(behaviour.get("video_url")),
            has_clip=bool(
                clip["key"]
                or clip["url"]
                or clip["path"]
                or _str(behaviour.get("video_url"))
            ),
        )
        if video_url:
            behaviour["video_url"] = video_url
            alert["behaviour"] = behaviour
        channel_id = _str(payload.get("camera_id")) or _str(channel.get("channel_id"))
        if channel_id:
            channel["channel_id"] = channel_id
            alert["channel_info"] = channel
        out["alert_info"] = alert
        return out
    body = normalize_payload(payload)
    trigger = _str(body.get("trigger_type"))
    ts = _capture_unix(_str(body.get("trigger_time")))
    channel_name = _str(body.get("camera_name")) or _str(body.get("camera_id"))
    ipc = _str(body.get("ipc_addr")) or ipc_addr_from_uri(_str(body.get("camera_uri")))
    device_name = _str(body.get("node_id")) or "nexus-deepstream"
    event_id = _str(body.get("event_id"))
    clip = clip_from_payload(body)
    video_url = _refresh_campus_video_url(
        event_id,
        _str(body.get("video_url")),
        has_clip=bool(clip["key"] or clip["url"] or clip["path"]),
    )
    incident = trigger not in {"", "stream_silent"}
    behaviour: dict[str, Any] = {"capture_time": ts}
    if video_url:
        behaviour["video_url"] = video_url
    if incident:
        behaviour["algo_model"] = _ALGO_MODEL.get(trigger, trigger)
    channel_info: dict[str, Any] = {
        "channel_name": channel_name,
        "ipc_addr": ipc,
    }
    camera_id = _str(body.get("camera_id"))
    if camera_id:
        channel_info["channel_id"] = camera_id
    alert_info: dict[str, Any] = {
        "type": 1 if incident else (trigger or "stream_silent"),
        "device_info": {
            "device_name": device_name,
            "device_sn": device_name,
        },
        "channel_info": channel_info,
        "behaviour": behaviour,
    }
    envelope: dict[str, Any] = {
        "source": "nexus_deepstream",
        "time_received": _time_received(ts),
        "alert_info": alert_info,
    }
    if event_id:
        envelope["event_id"] = event_id
    return envelope


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
    camera_uri: str = "",
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
            "camera_uri": camera_uri,
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
