"""Runtime settings (env + persisted JSON overrides)."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


def _default_data_dir() -> Path:
    raw = (os.environ.get("NEXUS_DS_DATA_DIR") or "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parent.parent / "data"


class NodeSettings(BaseModel):
    """Editable node config (UI + API). Persisted to data/settings.json."""

    node_id: str = Field(default="ds-1", min_length=1, max_length=64)
    node_name: str = Field(default="DeepStream Node 1", max_length=128)
    api_token: str = Field(default="", description="If set, require Bearer token on API")

    # Pull cameras from backend (optional). Local CRUD always works.
    cameras_url: str = Field(
        default="",
        description="GET JSON {cameras:[...]} from Django / another source",
    )
    cameras_poll_sec: int = Field(default=60, ge=0, le=3600)

    # Where to POST triggers (primary for multi-node product)
    triggers_url: str = Field(
        default="",
        description="POST trigger payload (Campus / webhook)",
    )
    triggers_timeout_sec: float = Field(default=5.0, ge=1.0, le=120.0)

    enable_http_sink: bool = True
    enable_log_sink: bool = True

    # Trigger / record / pipeline (same semantics as Campus Redis config)
    trigger_mode: str = "convergence"
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
            os.environ.get("DEEPSTREAM_DEBUG_DIR")
            or str(_default_data_dir() / "debug")
        )
    )


def load_env_bootstrap() -> EnvBootstrap:
    host = (os.environ.get("NEXUS_DS_HOST") or "0.0.0.0").strip()
    port = int(os.environ.get("NEXUS_DS_PORT") or "8080")
    return EnvBootstrap(host=host, port=port)
