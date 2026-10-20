"""Scenario lab verdicts and clip selection. No DeepStream or database."""

from __future__ import annotations

from pathlib import Path

from app.scenario_lab import clip_ready, judge, materialize_clip
from app.scenario_lab_run import lab_config
from app.settings import NodeSettings


def test_judge_hit_miss_and_missing_model() -> None:
    assert judge("presence", ["presence", "convergence"]) == "hit"
    assert judge("vif", ["presence"]) == "miss"
    assert judge("fall", ["presence"]) == "no_model"
    assert judge("smoke", []) == "no_model"
    assert judge("stream_silent", ["presence"]) == "file_skip"


def test_clip_ready_needs_minio_or_local_file(tmp_path: Path) -> None:
    assert clip_ready({}) is False
    assert clip_ready({"clip": {"key": "incidents/a.mp4"}}) is True
    missing = tmp_path / "gone.mp4"
    assert clip_ready({"clip": {"path": str(missing)}}) is False
    local = tmp_path / "here.mp4"
    local.write_bytes(b"mp4")
    assert clip_ready({"clip": {"path": str(local)}}) is True


def test_local_clip_is_reused(tmp_path: Path) -> None:
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"mp4")
    path, owned = materialize_clip(
        {"path": str(src), "event_id": "evt-1"},
        tmp_path / "cache",
    )
    assert path == src
    assert owned is False
    assert src.is_file()


def test_lab_config_is_a_file_source(tmp_path: Path) -> None:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"x")
    cfg, cameras = lab_config(NodeSettings(), path)
    assert cameras[0].main_uri.startswith("file:")
    assert cfg.pipeline.live_source is False
    assert "presence" in cfg.trigger.enabled
    assert cfg.trigger.cooldown_s == 0
