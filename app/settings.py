"""Runtime settings (env + persisted JSON overrides)."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator

from app.trigger_thresholds import merge_trigger_thresholds, sync_flat_from_profiles
from app.trigger_types import DEFAULT_ENABLED_TRIGGERS, normalize_enabled_triggers


def _default_data_dir() -> Path:
    raw = (os.environ.get("NEXUS_DS_DATA_DIR") or "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parent.parent / "data"


class NodeSettings(BaseModel):
    """Editable node config (UI + API). Persisted to data/settings.json."""

    node_id: str = Field(default="ds-1", min_length=1, max_length=64)
    node_name: str = Field(default="DeepStream Node 1", max_length=128)

    # Where to POST triggers (primary for multi-node product)
    triggers_url: str = Field(
        default="",
        description="POST trigger payload (Campus / webhook)",
    )
    triggers_timeout_sec: float = Field(default=5.0, ge=1.0, le=120.0)

    enable_http_sink: bool = True
    enable_log_sink: bool = True
    enable_clip_record: bool = True

    # Trigger / record / pipeline (same semantics as Campus Redis config)
    trigger_mode: str = "convergence"
    enabled_triggers: list[str] = Field(
        default_factory=lambda: list(DEFAULT_ENABLED_TRIGGERS)
    )
    min_tracks: int = 2
    converge_dist_bh: float = 1.5
    speed_thresh_bh: float = 2.0
    sustain_s: float = 0.4
    cooldown_s: float = 30.0
    presence_min_people: int = 1
    presence_sustain_s: float = 2.0
    vif_iou_thresh: float = 0.25
    vif_sustain_s: float = 0.3
    clip_pre_s: float = 5.0
    clip_post_s: float = 15.0
    infer_interval: int = 2
    conf_threshold: float = 0.25
    reconnect_s: float = 10.0
    stream_silent_s: float = 30.0
    mux_width: int = 1280
    mux_height: int = 720
    person_class_id: int = 0
    detector_model: str = "yolo11n"

    # Worker
    auto_start_pipeline: bool = True
    max_streams: int = Field(default=16, ge=1, le=128)

    # Per trigger-type thresholds (presence / convergence / vif / stream_silent).
    trigger_thresholds: dict[str, dict[str, float | int]] = Field(default_factory=dict)

    @field_validator("enabled_triggers", mode="before")
    @classmethod
    def _enabled_triggers(cls, value: object) -> list[str]:
        return normalize_enabled_triggers(value)

    @model_validator(mode="after")
    def _normalize_threshold_profiles(self) -> NodeSettings:
        self.trigger_thresholds = merge_trigger_thresholds(
            self, self.trigger_thresholds
        )
        sync_flat_from_profiles(self)
        return self


class EnvBootstrap(BaseModel):
    """Boot-time env (not edited in UI)."""

    host: str = "0.0.0.0"
    port: int = 8080
    data_dir: Path = Field(default_factory=_default_data_dir)
    yolo_dir: Path = Field(
        default_factory=lambda: Path(
            os.environ.get("DEEPSTREAM_YOLO_DIR")
            or str(Path(__file__).resolve().parent.parent / "models" / "yolo11n")
        )
    )
    work_dir: Path = Field(
        default_factory=lambda: Path(
            os.environ.get("DEEPSTREAM_WORK_DIR") or "/tmp/nexus_deepstream"
        )
    )
    debug_dir: Path = Field(
        default_factory=lambda: Path(
            os.environ.get("DEEPSTREAM_DEBUG_DIR") or str(_default_data_dir() / "debug")
        )
    )


def load_env_bootstrap() -> EnvBootstrap:
    host = (os.environ.get("NEXUS_DS_HOST") or "0.0.0.0").strip()
    port = int(os.environ.get("NEXUS_DS_PORT") or "8080")
    return EnvBootstrap(host=host, port=port)
