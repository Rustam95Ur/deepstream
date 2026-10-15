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
    frame, lines = grab_jpeg(spec.main_uri)
    from_ring = False
    if frame is None:
        frame, ring_lines = _frame_from_ring(spec, configs)
        lines.extend(ring_lines)
        from_ring = frame is not None
    debug = "\n".join(lines)
    if not frame:
        return CameraProbeOut(ok=False, detail="Поток не отвечает", debug=debug)

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
        debug=debug,
    )


def _frame_from_ring(
    camera: CameraConfig,
    cameras: dict[str, CameraConfig],
) -> tuple[bytes | None, list[str]]:
    now = time.time()
    lines = ["запись потока:"]
    found = False
    for path in recent_ring_segments(camera, cameras):
        found = True
        try:
            age = now - path.stat().st_mtime
        except OSError as exc:
            lines.append(f"{path.name}: не прочитан ({exc.__class__.__name__})")
            continue
        if age > _RING_FRESH_S:
            lines.append(f"{path.name}: устарел, {age:.0f} с назад")
            break
        frame, grab_lines = grab_jpeg(str(path), tail=True, timeout_sec=8.0)
        lines.append(f"{path.name}: возраст {age:.0f} с")
        lines.extend(f"  {line}" for line in grab_lines)
        if frame:
            return frame, lines
    if not found:
        lines.append("свежих сегментов нет")
    return None, lines


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
