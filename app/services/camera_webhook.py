"""Send one camera's current stream to the webhook as an incident."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from app.campus.urls import public_clip_url
from app.db import db_enabled
from app.ds.clip import capture_current_clip
from app.ds.config import CameraConfig
from app.ds.payload import attach_clip, build_payload
from app.history import record_trigger
from app.minio_store import build_incident_object_key, get_minio_store
from app.schemas import CameraWebhookOut
from app.services.cameras import get_camera
from app.storage import get_store
from app.webhooks import enqueue_payload, list_enabled_webhooks

logger = logging.getLogger(__name__)

_MAX_CLIP_S = 30.0
_MANUAL_TRIGGER = "manual"


def send_current_stream(camera_id: str) -> CameraWebhookOut:
    cam = get_camera(camera_id)
    settings = get_store().get_settings()
    if not settings.enable_http_sink:
        raise HTTPException(status_code=400, detail="отправка в вебхук выключена")
    if not db_enabled():
        raise HTTPException(status_code=503, detail="Postgres не настроен")
    if not list_enabled_webhooks():
        raise HTTPException(status_code=400, detail="нет включённых вебхуков")

    duration = min(
        _MAX_CLIP_S,
        max(3.0, float(settings.clip_pre_s) + float(settings.clip_post_s)),
    )
    configs = _configs()
    spec = configs.get(cam.id) or CameraConfig(
        camera_id=cam.id,
        main_uri=cam.main_uri,
        enabled=cam.enabled,
        name=cam.name or cam.id,
    )
    event_id = str(uuid4())
    clip = capture_current_clip(
        camera=spec,
        cameras=configs,
        event_id=event_id,
        duration_s=duration,
    )
    path = str(clip.get("clip_path") or "")
    if clip.get("status") != "ok" or not path:
        raise HTTPException(
            status_code=400,
            detail=str(clip.get("error") or "не удалось снять текущий поток"),
        )

    payload = build_payload(
        camera_id=cam.id,
        camera_name=cam.name or cam.id,
        camera_uri=cam.main_uri,
        trigger_type=_MANUAL_TRIGGER,
        pre_s=float(settings.clip_pre_s),
        post_s=float(settings.clip_post_s),
        evidence={"manual": True, "source": "current_stream"},
        event_id=event_id,
        node_id=settings.node_id,
    )
    _attach_stored_clip(
        payload,
        path,
        camera_id=cam.id,
        camera_name=cam.name or cam.id,
        event_id=event_id,
    )
    record_trigger(payload)
    queued = enqueue_payload(payload, reason="manual")
    if queued < 1:
        raise HTTPException(status_code=400, detail="отправка не поставлена в очередь")
    return CameraWebhookOut(event_id=event_id, queued=queued)


def _configs() -> dict[str, CameraConfig]:
    return {
        item.id: CameraConfig(
            camera_id=item.id,
            main_uri=item.main_uri,
            enabled=item.enabled,
            name=item.name or item.id,
        )
        for item in get_store().list_cameras()
    }


def _attach_stored_clip(
    payload: dict[str, Any],
    path: str,
    *,
    camera_id: str,
    camera_name: str,
    event_id: str,
) -> None:
    store = get_minio_store()
    url = public_clip_url(event_id)
    key = ""
    bucket = ""
    file_path = Path(path)
    if store.enabled:
        key = build_incident_object_key(
            camera_id=camera_id,
            camera_name=camera_name,
            event_id=event_id,
            prefix=store.config.key_prefix,
        )
        if store.upload_file(file_path, key):
            bucket = store.config.bucket
            url = url or store.object_url(key)
        else:
            logger.warning("manual webhook: minio upload failed event=%s", event_id)
            key = ""
    attach_clip(payload, url=url or "", bucket=bucket, key=key, path=str(file_path))
