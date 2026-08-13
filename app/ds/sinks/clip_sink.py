"""Cut clip from ring-buffer, upload to MinIO, then forward the trigger."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.ds.clip import build_clip_from_payload
from app.ds.config import CameraConfig
from app.minio_store import build_incident_object_key, get_minio_store

logger = logging.getLogger(__name__)

_SKIP_TRIGGER_TYPES = frozenset({"stream_silent"})


class IncidentClipSink:
    """
    Campus rtsp_writer path: wait pre/post → concat ring-buffer segments →
    MinIO → attach ``video_url`` / ``video_key`` / ``video_bucket`` → HTTP.
    """

    def __init__(
        self,
        inner: Any,
        cameras: list[CameraConfig],
        *,
        enabled: bool = True,
    ) -> None:
        self.inner = inner
        self.source_video = getattr(inner, "source_video", None)
        self._by_id = {c.camera_id: c for c in cameras}
        self._enabled = enabled

    def send(self, payload: dict[str, Any]) -> str | None:
        if self._should_clip(payload):
            self._attach_clip(payload)
        try:
            from app.history import record_trigger

            record_trigger(payload)
        except Exception:
            logger.exception("failed to persist trigger history")
        return self.inner.send(payload)

    def close(self) -> None:
        closer = getattr(self.inner, "close", None)
        if callable(closer):
            closer()

    def _should_clip(self, payload: dict[str, Any]) -> bool:
        if not self._enabled:
            return False
        if str(payload.get("category") or "") == "error":
            return False
        if str(payload.get("trigger_type") or "") in _SKIP_TRIGGER_TYPES:
            return False
        if payload.get("video_url") or payload.get("video_key"):
            return False
        camera_id = str(payload.get("camera_id") or "").strip()
        if camera_id not in self._by_id:
            logger.warning("incident clip: unknown camera_id=%s", camera_id)
            return False
        return True

    def _attach_clip(self, payload: dict[str, Any]) -> None:
        store = get_minio_store()
        event_id = str(payload.get("event_id") or "")
        camera_id = str(payload.get("camera_id") or "").strip()
        cam = self._by_id.get(camera_id)

        clip = build_clip_from_payload(payload, self._by_id)
        if clip.get("status") != "ok" or not clip.get("clip_path"):
            err = clip.get("error") or "clip failed"
            logger.error(
                "incident clip failed camera=%s event=%s error=%s",
                camera_id,
                event_id,
                err,
            )
            evidence = dict(payload.get("evidence") or {})
            evidence["clip_error"] = err
            payload["evidence"] = evidence
            from app.history import record_send

            record_send(
                event_id=event_id,
                sink="clip",
                url="",
                status="error",
                error=err,
            )
            return

        path = Path(str(clip["clip_path"]))
        if not store.enabled:
            logger.warning("incident clip: MinIO is not configured — skip upload")
            evidence = dict(payload.get("evidence") or {})
            evidence["clip_error"] = "minio_not_configured"
            payload["evidence"] = evidence
            return

        key = build_incident_object_key(
            camera_id=camera_id,
            camera_name=(cam.name if cam else camera_id) or camera_id,
            event_id=event_id,
            prefix=store.config.key_prefix,
        )
        if not store.upload_file(path, key):
            evidence = dict(payload.get("evidence") or {})
            evidence["clip_error"] = "minio_upload_failed"
            payload["evidence"] = evidence
            from app.history import record_send

            record_send(
                event_id=event_id,
                sink="minio",
                url="",
                status="error",
                error="minio_upload_failed",
            )
            return

        url = store.object_url(key)
        payload["video_bucket"] = store.config.bucket
        payload["video_key"] = key
        if url:
            payload["video_url"] = url
        logger.info(
            "incident clip uploaded camera=%s event=%s key=%s segments=%s",
            camera_id,
            event_id,
            key,
            clip.get("segments"),
        )
        from app.history import record_send

        record_send(
            event_id=event_id,
            sink="minio",
            url=url or key,
            status="ok",
        )
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("incident clip: failed to remove local clip %s", path)
