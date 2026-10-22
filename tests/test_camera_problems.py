"""Overview-style camera problems, without a video process."""

from __future__ import annotations

from app.schemas import (
    CameraStreamOut,
    RingCameraHealthOut,
    VideoHealthOut,
    WorkerStatusOut,
)
from app.services.camera_problems import describe_camera, explain_gst, is_fault


class _Cam:
    def __init__(self, cam_id: str, uri: str, *, name: str = "", enabled: bool = True):
        self.id = cam_id
        self.name = name or cam_id
        self.main_uri = uri
        self.enabled = enabled


def _health(**kwargs) -> VideoHealthOut:
    pipe = kwargs.pop(
        "pipeline",
        WorkerStatusOut(running=True, available=True, camera_ids=["gate"]),
    )
    return VideoHealthOut(
        status=kwargs.pop("status", "ok"),
        gst_available=True,
        clip_record=kwargs.pop("clip_record", True),
        ring_running=kwargs.pop("ring_running", True),
        pipeline=pipe,
        cameras=kwargs.pop("cameras", []),
        streams=kwargs.pop("streams", []),
    )


def test_waiting_stream_and_restarts_match_the_overview() -> None:
    cam = _Cam("gate", "rtsp://10.0.0.12/stream", name="Калитка")
    health = _health(
        streams=[CameraStreamOut(camera_id="gate", state="waiting")],
        cameras=[
            RingCameraHealthOut(
                camera_id="gate", name="Калитка", alive=True, restarts=4
            )
        ],
    )
    row = describe_camera(cam, health)
    assert row["detect"] == "ждёт"
    assert row["record"] == "пишет"
    assert row["problem"] == "поток ещё открывается · запись идёт, перезапусков 4"
    assert is_fault(row["problem"])
    assert row["ok"] is False


def test_dead_recorder_translates_rtsp_eof() -> None:
    cam = _Cam("yard", "rtsp://10.0.0.13/stream")
    health = _health(
        pipeline=WorkerStatusOut(running=True, available=True, camera_ids=["yard"]),
        streams=[CameraStreamOut(camera_id="yard", state="live", last_frame_age_s=1)],
        cameras=[
            RingCameraHealthOut(
                camera_id="yard",
                name="yard",
                alive=False,
                last_error="gst error: end-of-file from rtspsrc",
            )
        ],
    )
    row = describe_camera(cam, health)
    assert row["record"] == "упал"
    assert row["problem"] == "запись упала: камера закрыла RTSP"
    assert explain_gst("connection refused") == "соединение отклонено"


def test_live_camera_is_not_a_fault() -> None:
    cam = _Cam("ok", "rtsp://10.0.0.14/stream")
    health = _health(
        pipeline=WorkerStatusOut(running=True, available=True, camera_ids=["ok"]),
        streams=[CameraStreamOut(camera_id="ok", state="live", last_frame_age_s=1)],
        cameras=[RingCameraHealthOut(camera_id="ok", name="ok", alive=True)],
    )
    row = describe_camera(cam, health)
    assert row["problem"] == ""
    assert row["ok"] is True
    assert is_fault(row["problem"]) is False


def test_unreachable_video_is_down_for_every_camera() -> None:
    cam = _Cam("gate", "rtsp://10.0.0.12/stream")
    row = describe_camera(cam, None)
    assert row["detect"] == "нет связи"
    assert row["record"] == "нет связи"
    assert row["problem"] == "нет связи с video-контейнером"
    offline = _health(status="error")
    assert describe_camera(cam, offline)["problem"] == "нет связи с video-контейнером"


def test_disabled_camera_is_not_a_stream_fault() -> None:
    cam = _Cam("old", "rtsp://10.0.0.15/stream", enabled=False)
    row = describe_camera(cam, _health())
    assert row["problem"] == "выключена"
    assert is_fault(row["problem"]) is False
