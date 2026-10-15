"""Check one camera's current stream and return a single frame."""

from __future__ import annotations

import base64
import time

from app.ds.clip import grab_jpeg, recent_ring_segments
from app.ds.config import CameraConfig
from app.ds.rtsp import probe_video
from app.schemas import CameraProbeOut
from app.services.cameras import get_camera
from app.storage import get_store

_RING_FRESH_S = 20.0


def probe_current_stream(camera_id: str) -> CameraProbeOut:
    cam = get_camera(camera_id)
    configs = _configs()
    spec = configs.get(cam.id) or CameraConfig(
        camera_id=cam.id,
        main_uri=cam.main_uri,
        enabled=cam.enabled,
        name=cam.name or cam.id,
    )
    frame = grab_jpeg(spec.main_uri)
    from_ring = False
    if frame is None:
        frame = _frame_from_ring(spec, configs)
        from_ring = frame is not None
    if not frame:
        return CameraProbeOut(ok=False, detail="Поток не отвечает")

    meta = probe_video(spec.main_uri, timeout_sec=4.0) if not from_ring else {}
    detail = (
        "Адрес потока не ответил. Показан последний кадр записи."
        if from_ring
        else "Поток отвечает"
    )
    return CameraProbeOut(
        ok=True,
        detail=detail,
        codec=str(meta.get("codec") or ""),
        width=int(meta.get("width") or 0),
        height=int(meta.get("height") or 0),
        fps=float(meta.get("fps") or 0),
        image=base64.b64encode(frame).decode("ascii"),
    )


def _frame_from_ring(
    camera: CameraConfig,
    cameras: dict[str, CameraConfig],
) -> bytes | None:
    now = time.time()
    for path in recent_ring_segments(camera, cameras):
        try:
            age = now - path.stat().st_mtime
        except OSError:
            continue
        if age > _RING_FRESH_S:
            break
        frame = grab_jpeg(str(path), tail=True, timeout_sec=8.0)
        if frame:
            return frame
    return None


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
