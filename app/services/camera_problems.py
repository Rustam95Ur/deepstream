"""Per-camera problems, same wording as the overview stream table."""

from __future__ import annotations

from typing import Any, Protocol

from app.schemas import CameraStreamOut, RingCameraHealthOut, VideoHealthOut


class _Camera(Protocol):
    id: str
    name: str
    main_uri: str
    enabled: bool


def is_fault(problem: str) -> bool:
    """A switched-off camera is a state, not a stream failure."""
    return bool(problem) and problem != "выключена"


def describe_camera(cam: _Camera, health: VideoHealthOut | None) -> dict[str, Any]:
    detect = _detect_label(cam, health)
    record = _ring_label(cam, health)
    problem = _stream_problem(cam, health)
    row = _ring_of(cam.id, health)
    return {
        "id": cam.id,
        "name": cam.name or cam.id,
        "uri": cam.main_uri or "",
        "enabled": cam.enabled,
        "detect": detect,
        "record": record,
        "problem": problem,
        "ok": not is_fault(problem),
        "last_error": (row.last_error if row else "") or "",
    }


def _age_text(sec: float | None) -> str:
    if sec is None:
        return ""
    whole = max(0, int(sec + 0.5))
    if whole < 60:
        return f"{whole} с"
    minutes, rem = divmod(whole, 60)
    if rem:
        return f"{minutes} мин {rem} с"
    return f"{minutes} мин"


def explain_gst(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    folded = text.lower()
    if "end-of-file" in folded or "end of file" in folded:
        return "камера закрыла RTSP"
    if "parse error" in folded:
        return "камера ответила не RTSP"
    if "connection refused" in folded:
        return "соединение отклонено"
    if "timed out" in folded or "timeout" in folded:
        return "таймаут RTSP"
    if "not found" in folded or "404" in folded:
        return "поток не найден"
    if "no data" in folded:
        return "источник не отдаёт кадры"
    if (
        "could not read" in folded
        or "could not write" in folded
        or "system error" in folded
    ):
        return "нет связи с камерой"
    if len(text) > 180:
        return f"{text[:177]}…"
    return text


def _reachable(health: VideoHealthOut | None) -> bool:
    return health is not None and health.status == "ok"


def _pipeline_ids(health: VideoHealthOut | None) -> set[str]:
    if not _reachable(health) or health is None:
        return set()
    return set(health.pipeline.camera_ids or [])


def _skip_reason(cam: _Camera, health: VideoHealthOut | None) -> str:
    if not _reachable(health) or health is None:
        return ""
    for row in health.pipeline.skipped or []:
        if row.camera_id == cam.id and row.reason:
            return row.reason
    return ""


def _stream_of(camera_id: str, health: VideoHealthOut | None) -> CameraStreamOut | None:
    if not _reachable(health) or health is None:
        return None
    for row in health.streams or []:
        if row.camera_id == camera_id:
            return row
    return None


def _ring_of(
    camera_id: str, health: VideoHealthOut | None
) -> RingCameraHealthOut | None:
    if not _reachable(health) or health is None:
        return None
    for row in health.cameras or []:
        if row.camera_id == camera_id:
            return row
    return None


def _is_rtsp(uri: str) -> bool:
    return (uri or "").strip().lower().startswith("rtsp://")


def _pipe_reason(cam: _Camera, health: VideoHealthOut | None) -> str:
    if cam.id in _pipeline_ids(health):
        return ""
    return _skip_reason(cam, health) or (
        "не в текущем графе" if cam.enabled else "выключена"
    )


def _detect_state(cam: _Camera, health: VideoHealthOut | None) -> str:
    if not _reachable(health):
        return "down"
    if cam.id not in _pipeline_ids(health):
        return "out"
    stream = _stream_of(cam.id, health)
    return (stream.state if stream else "") or "unknown"


def _detect_label(cam: _Camera, health: VideoHealthOut | None) -> str:
    state = _detect_state(cam, health)
    return {
        "live": "кадры",
        "starting": "старт",
        "waiting": "ждёт",
        "silent": "молчит",
        "closed": "нет потока",
        "down": "нет связи",
        "out": "нет",
    }.get(state, "нет данных")


def _detect_problem(cam: _Camera, health: VideoHealthOut | None) -> str:
    state = _detect_state(cam, health)
    stream = _stream_of(cam.id, health)
    age = _age_text(stream.last_frame_age_s if stream else None)
    if state == "down":
        return "нет связи с video-контейнером"
    if state == "out":
        return _pipe_reason(cam, health)
    if state == "starting":
        up = _age_text(stream.pipeline_uptime_s if stream else None)
        if up:
            return f"пайплайн ещё поднимается, кадров нет уже {up}"
        return "пайплайн ещё поднимается, кадров нет"
    if state == "waiting":
        return "поток ещё открывается"
    if state == "closed":
        return "кадров не было — RTSP не открылся"
    if state == "silent":
        if age:
            return f"нет кадров {age} — источник молчит, идёт переподключение"
        return "источник молчит, идёт переподключение"
    if state == "unknown":
        return "нет данных о кадрах"
    return ""


def _ring_kind(cam: _Camera, health: VideoHealthOut | None) -> str:
    if not _reachable(health) or health is None:
        return "down"
    if not _is_rtsp(cam.main_uri):
        return "skip"
    if not health.clip_record:
        return "off"
    row = _ring_of(cam.id, health)
    if not health.ring_running or row is None:
        return "absent"
    if not row.alive:
        return "dead"
    if row.stalled:
        return "stalled"
    return "live"


def _ring_label(cam: _Camera, health: VideoHealthOut | None) -> str:
    return {
        "live": "пишет",
        "stalled": "застой",
        "dead": "упал",
        "skip": "не RTSP",
        "off": "выкл",
        "down": "нет связи",
    }.get(_ring_kind(cam, health), "нет записи")


def _ring_problem(cam: _Camera, health: VideoHealthOut | None) -> str:
    kind = _ring_kind(cam, health)
    row = _ring_of(cam.id, health)
    why = explain_gst(row.last_error if row else "")
    age = _age_text(row.last_segment_age_s if row else None)
    if kind == "dead":
        return f"запись упала: {why}" if why else "запись упала"
    if kind == "stalled":
        stall = f"запись встала, сегмент {age} назад" if age else "запись встала"
        return f"{stall}: {why}" if why else stall
    if kind == "absent" and _is_rtsp(cam.main_uri):
        return "запись не запущена"
    if kind == "live" and row is not None and row.restarts > 0:
        return f"запись идёт, перезапусков {row.restarts}"
    return ""


def _stream_problem(cam: _Camera, health: VideoHealthOut | None) -> str:
    if not cam.enabled:
        return _pipe_reason(cam, health) or "выключена"
    parts = [
        part
        for part in (
            _detect_problem(cam, health),
            _ring_problem(cam, health),
        )
        if part
    ]
    return " · ".join(parts)
