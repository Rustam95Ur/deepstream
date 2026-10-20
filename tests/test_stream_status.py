"""Per-camera decode health exposed to the admin."""

from __future__ import annotations

import time

from app.ds.config import AppConfig, CameraConfig, PipelineConfig
from app.ds.stream_status import bind, snapshot, unbind
from app.ds.triggers import TriggerEngine


def _engine() -> TriggerEngine:
    cams = [
        CameraConfig(camera_id="a", main_uri="rtsp://a", name="Камера A"),
        CameraConfig(camera_id="b", main_uri="rtsp://b", name="Камера B"),
    ]
    cfg = AppConfig(cameras=cams, pipeline=PipelineConfig(stream_silent_s=30))
    return TriggerEngine(cfg, cams, sink=None)


def test_no_frames_yet_is_starting() -> None:
    rows = {row["camera_id"]: row for row in _engine().stream_rows()}
    assert rows["a"]["state"] == "starting"
    assert rows["b"]["state"] == "starting"
    assert rows["a"]["last_frame_age_s"] is None


def test_one_live_other_still_opening() -> None:
    engine = _engine()
    engine.note_frame(0)
    rows = {row["camera_id"]: row for row in engine.stream_rows()}
    assert rows["a"]["state"] == "live"
    assert rows["a"]["last_frame_age_s"] is not None
    assert rows["b"]["state"] == "waiting"


def test_silent_and_never_opened() -> None:
    engine = _engine()
    now = time.monotonic()
    engine._first_frame_mono = now - 40
    engine.by_pad[0].saw_frame = True
    engine.by_pad[0].last_frame_ts = now - 40
    rows = {row["camera_id"]: row for row in engine.stream_rows()}
    assert rows["a"]["state"] == "silent"
    assert rows["a"]["last_frame_age_s"] >= 30
    assert rows["b"]["state"] == "closed"


def test_snapshot_follows_the_bound_engine() -> None:
    engine = _engine()
    bind(engine)
    try:
        assert snapshot()[0]["state"] == "starting"
        engine.note_frame(1)
        states = {row["camera_id"]: row["state"] for row in snapshot()}
        assert states["b"] == "live"
    finally:
        unbind(engine)
    assert snapshot() == []
