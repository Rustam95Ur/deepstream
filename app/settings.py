"""Runtime settings (env + persisted JSON overrides)."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator

from app.runtime_env import get_runtime_env
from app.trigger_thresholds import merge_trigger_thresholds, sync_flat_from_profiles
from app.trigger_types import DEFAULT_ENABLED_TRIGGERS, normalize_enabled_triggers

DEFAULT_BILLING_VALIDATE_URL = "http://localhost/api/v1/public/keys/validate"


def _default_data_dir() -> Path:
    return get_runtime_env().data_dir


class NodeSettings(BaseModel):
    """Editable node config (UI + API). Persisted to data/settings.json."""

    node_id: str = Field(default="ds-1", min_length=1, max_length=64)
    node_name: str = Field(default="DeepStream Node 1", max_length=128)

    # Seed-only: used once to create the first webhook when the table is empty.
    # Live outbound URLs come from the webhooks table / UI.
    triggers_url: str = Field(
        default="",
        description="Seed webhook URL when webhooks table is empty (legacy)",
    )
    triggers_timeout_sec: float = Field(default=5.0, ge=1.0, le=120.0)

    enable_http_sink: bool = True
    enable_log_sink: bool = True
    enable_clip_record: bool = True

    billing_url: str = Field(
        default=DEFAULT_BILLING_VALIDATE_URL,
        description="Nexus Billing POST /api/v1/public/keys/validate",
    )
    billing_api_key: str = Field(default="", max_length=256)
    billing_timeout_sec: float = Field(default=5.0, ge=1.0, le=30.0)

    @field_validator("billing_url", mode="before")
    @classmethod
    def _billing_url(cls, value: object) -> str:
        raw = str(value).strip() if value is not None else ""
        return raw or DEFAULT_BILLING_VALIDATE_URL

    @field_validator("billing_api_key", mode="before")
    @classmethod
    def _billing_api_key(cls, value: object) -> str:
        return str(value).strip() if value is not None else ""

    # Trigger / record / pipeline (same semantics as Campus Redis config)
    trigger_mode: str = "convergence"
    enabled_triggers: list[str] = Field(
        default_factory=lambda: list(DEFAULT_ENABLED_TRIGGERS)
    )
    # Flat threshold mirrors — kept for API/settings.json compat.
    # Source of truth is ``trigger_thresholds``; validator syncs both ways once.
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

    # Per trigger-type thresholds (canonical). Flat fields above are mirrors.
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
    """Boot-time paths and listen address (subset of RuntimeEnv for Store/UI)."""

    host: str = "0.0.0.0"
    port: int = 8080
    data_dir: Path = Field(default_factory=_default_data_dir)
    yolo_dir: Path = Field(
        default_factory=lambda: get_runtime_env().yolo_dir
    )
    work_dir: Path = Field(
        default_factory=lambda: get_runtime_env().work_dir
    )
    debug_dir: Path = Field(
        default_factory=lambda: get_runtime_env().debug_dir
    )


def load_env_bootstrap() -> EnvBootstrap:
    rt = get_runtime_env()
    return EnvBootstrap(
        host=rt.host,
        port=rt.port,
        data_dir=rt.data_dir,
        yolo_dir=rt.yolo_dir,
        work_dir=rt.work_dir,
        debug_dir=rt.debug_dir,
    )
