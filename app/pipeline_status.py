"""Why a camera is missing from the live DeepStream pad list."""

from __future__ import annotations

from app.schemas import CameraOut, CameraSkipOut, LogLineOut, WorkerStatusOut
from app.settings import NodeSettings


def skip_reasons(
    cameras: list[CameraOut],
    status: WorkerStatusOut,
    settings: NodeSettings,
) -> list[CameraSkipOut]:
    in_pipe = set(status.camera_ids)
    enabled = [c for c in cameras if c.enabled]
    cap = max(1, int(settings.max_streams))
    desired = {c.id for c in enabled[:cap]}
    out: list[CameraSkipOut] = []
    for cam in cameras:
        if cam.id in in_pipe:
            continue
        if not cam.enabled:
            reason = "выключена"
        elif not (cam.main_uri or "").strip():
            reason = "нет URI"
        elif not status.available:
            reason = (status.last_error or status.detail or "video недоступен").strip()
        elif not status.running:
            reason = "pipeline остановлен"
        elif cam.id not in desired:
            reason = f"лимит max_streams={cap}"
        elif status.reload_pending:
            reason = "ждёт пересборки пайплайна"
        elif status.last_error:
            reason = status.last_error.strip()
        else:
            reason = "пайплайн ещё со старым списком камер"
        out.append(
            CameraSkipOut(
                camera_id=cam.id,
                name=(cam.name or cam.id).strip() or cam.id,
                reason=reason,
            )
        )
    return out


def attach_status(
    status: WorkerStatusOut,
    cameras: list[CameraOut],
    settings: NodeSettings,
) -> WorkerStatusOut:
    status.max_streams = int(settings.max_streams)
    status.skipped = skip_reasons(cameras, status, settings)
    return status


def as_log_lines(raw: list[object]) -> list[LogLineOut]:
    out: list[LogLineOut] = []
    for item in raw:
        if isinstance(item, LogLineOut):
            out.append(item)
            continue
        if not isinstance(item, dict):
            continue
        try:
            out.append(LogLineOut.model_validate(item))
        except Exception:
            msg = str(item.get("message") or "").strip()
            if msg:
                out.append(LogLineOut(level="WARNING", logger="app", message=msg))
    return out
