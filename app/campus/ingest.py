"""SmartBox-shaped ingest envelope for Campus incident-ingest."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.campus.cameras import CameraResolver, get_camera_resolver
from app.campus.urls import refresh_video_url
from app.ds.payload import (
    CLIP_META_KEY,
    clip_from_payload,
    ipc_addr_from_uri,
    normalize_payload,
)

# Campus types (incident_type). Unknown trigger names are sent as-is.
ALGO_MODEL = {
    "vif": "Драки",
    "convergence": "Драки",
    "fall": "Падение",
    "smoke": "Курение",
    "manual": "Драки",
}


def _str(value: Any) -> str:
    return str(value or "").strip()


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


def _resolve_external_cam_id(
    payload: dict[str, Any],
    channel: dict[str, Any],
    resolver: CameraResolver,
) -> str:
    """Campus matches ``channel_info.external_cam_id`` to ``Camera.external_cam_id``."""
    found = (
        _str(channel.get("external_cam_id"))
        or _str(payload.get("external_cam_id"))
        or _str(payload.get("camera_id"))
        or _str(channel.get("channel_id"))
        or _str(channel.get("camera_id"))
        or _str(channel.get("external_id"))
    )
    if found:
        return found
    return resolver.resolve_id(
        channel_name=_str(channel.get("channel_name"))
        or _str(payload.get("camera_name")),
        ipc_addr=_str(channel.get("ipc_addr")) or _str(payload.get("ipc_addr")),
    )


def to_smartbox_ingest(
    payload: dict[str, Any],
    *,
    resolver: CameraResolver | None = None,
) -> dict[str, Any]:
    """
    Campus ``POST /api/v1/incidents/`` body.

    Same shape as a SmartBox alert: envelope + ``alert_info`` with
    ``channel_info`` / ``behaviour.algo_model`` / ``behaviour.video_url``.
    Campus matches the node by ``device_info.device_sn`` and the camera by
    ``channel_info.external_cam_id``. Already-wrapped payloads get ``video_url``
    rewritten and ``external_cam_id`` filled from the local camera id.
    """
    cam_resolver = resolver if resolver is not None else get_camera_resolver()
    if isinstance(payload.get("alert_info"), dict):
        out = dict(payload)
        out.pop(CLIP_META_KEY, None)
        alert = dict(payload["alert_info"] or {})
        behaviour = dict(alert.get("behaviour") or {})
        channel = dict(alert.get("channel_info") or {})
        clip = clip_from_payload(payload)
        video_url = refresh_video_url(
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
        external_cam_id = _resolve_external_cam_id(payload, channel, cam_resolver)
        if external_cam_id:
            channel["external_cam_id"] = external_cam_id
            alert["channel_info"] = channel
            out["external_cam_id"] = external_cam_id
        device = dict(alert.get("device_info") or {})
        device_sn = _str(device.get("device_sn")) or _str(payload.get("node_id"))
        if device_sn:
            device["device_sn"] = device_sn
            alert["device_info"] = device
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
    video_url = refresh_video_url(
        event_id,
        _str(body.get("video_url")),
        has_clip=bool(clip["key"] or clip["url"] or clip["path"]),
    )
    incident = trigger not in {"", "stream_silent"}
    behaviour: dict[str, Any] = {"capture_time": ts}
    if video_url:
        behaviour["video_url"] = video_url
    if incident:
        behaviour["algo_model"] = ALGO_MODEL.get(trigger, trigger)
    external_cam_id = _str(body.get("camera_id")) or cam_resolver.resolve_id(
        channel_name=channel_name,
        ipc_addr=ipc,
    )
    channel_info: dict[str, Any] = {
        "channel_name": channel_name,
        "ipc_addr": ipc,
    }
    if external_cam_id:
        channel_info["external_cam_id"] = external_cam_id
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
    if external_cam_id:
        envelope["external_cam_id"] = external_cam_id
    return envelope
