"""Load DeepStream runtime config from settings + local cameras."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.trigger_types import (
    DEFAULT_ENABLED_TRIGGERS,
    camera_trigger_override,
    normalize_enabled_triggers,
)


@dataclass(slots=True)
class CameraConfig:
    camera_id: str
    main_uri: str
    enabled: bool = True
    name: str = ""
    enabled_triggers: frozenset[str] | None = None


@dataclass(slots=True)
class TriggerConfig:
    mode: str = "convergence"
    enabled: frozenset[str] = field(
        default_factory=lambda: frozenset(DEFAULT_ENABLED_TRIGGERS)
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

    def allows(self, kind: str) -> bool:
        return kind in self.enabled


@dataclass(slots=True)
class RecordConfig:
    clip_pre_s: float = 5.0
    clip_post_s: float = 15.0


@dataclass(slots=True)
class PipelineConfig:
    infer_interval: int = 2
    conf_threshold: float = 0.25
    live_source: bool = True
    reconnect_s: float = 10.0
    stream_silent_s: float = 30.0
    mux_width: int = 1280
    mux_height: int = 720
    person_class_id: int = 0
    detector_model: str = "yolo11n"


@dataclass(slots=True)
class AppConfig:
    cameras: list[CameraConfig] = field(default_factory=list)
    trigger: TriggerConfig = field(default_factory=TriggerConfig)
    record: RecordConfig = field(default_factory=RecordConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    node_id: str = ""

    @property
    def enabled_cameras(self) -> list[CameraConfig]:
        return [c for c in self.cameras if c.enabled and c.main_uri]


def app_config_from_dict(raw: dict[str, Any]) -> AppConfig:
    cameras: list[CameraConfig] = []
    for item in raw.get("cameras") or []:
        if not isinstance(item, dict):
            continue
        cam_id = str(item.get("id") or item.get("camera_id") or "").strip()
        uri = str(item.get("main_uri") or item.get("uri") or "").strip()
        if not cam_id or not uri:
            continue
        override = camera_trigger_override(item.get("enabled_triggers"))
        cameras.append(
            CameraConfig(
                camera_id=cam_id,
                main_uri=uri,
                enabled=bool(item.get("enabled", True)),
                name=str(item.get("name") or cam_id).strip() or cam_id,
                enabled_triggers=None if override is None else frozenset(override),
            )
        )

    trig_raw = raw.get("trigger") or {}
    rec_raw = raw.get("record") or {}
    pipe_raw = raw.get("pipeline") or {}

    trigger = TriggerConfig(
        mode=str(trig_raw.get("mode") or "convergence"),
        enabled=frozenset(normalize_enabled_triggers(trig_raw.get("enabled"))),
        min_tracks=int(trig_raw.get("min_tracks") or 2),
        converge_dist_bh=float(trig_raw.get("converge_dist_bh") or 1.5),
        speed_thresh_bh=float(trig_raw.get("speed_thresh_bh") or 2.0),
        sustain_s=float(trig_raw.get("sustain_s") or 0.4),
        cooldown_s=float(trig_raw.get("cooldown_s") or 30.0),
        presence_min_people=int(trig_raw.get("presence_min_people") or 1),
        presence_sustain_s=float(trig_raw.get("presence_sustain_s") or 2.0),
        vif_iou_thresh=float(trig_raw.get("vif_iou_thresh") or 0.25),
        vif_sustain_s=float(trig_raw.get("vif_sustain_s") or 0.3),
    )
    record = RecordConfig(
        clip_pre_s=float(rec_raw.get("clip_pre_s") or 5.0),
        clip_post_s=float(rec_raw.get("clip_post_s") or 15.0),
    )
    detector = (
        str(pipe_raw.get("detector_model") or "yolo11n").strip().lower() or "yolo11n"
    )
    pipeline = PipelineConfig(
        infer_interval=int(
            pipe_raw["infer_interval"]
            if pipe_raw.get("infer_interval") is not None
            else 2
        ),
        conf_threshold=float(pipe_raw.get("conf_threshold") or 0.25),
        live_source=bool(pipe_raw.get("live_source", True)),
        reconnect_s=float(pipe_raw.get("reconnect_s") or 10.0),
        stream_silent_s=float(pipe_raw.get("stream_silent_s") or 30.0),
        mux_width=int(pipe_raw.get("mux_width") or 1280),
        mux_height=int(pipe_raw.get("mux_height") or 720),
        person_class_id=int(
            pipe_raw["person_class_id"]
            if pipe_raw.get("person_class_id") is not None
            else 0
        ),
        detector_model=detector,
    )
    return AppConfig(
        cameras=cameras,
        trigger=trigger,
        record=record,
        pipeline=pipeline,
        node_id=str(raw.get("node_id") or ""),
    )


def app_config_from_settings(
    settings: Any,
    cameras: list[Any],
) -> AppConfig:
    """Build AppConfig from NodeSettings + CameraOut/CameraIn list."""
    cam_cfgs: list[CameraConfig] = []
    for cam in cameras:
        if hasattr(cam, "model_dump"):
            d = cam.model_dump()
        elif isinstance(cam, dict):
            d = cam
        else:
            continue
        cam_id = str(d.get("id") or "").strip()
        uri = str(d.get("main_uri") or "").strip()
        if not cam_id or not uri:
            continue
        override = camera_trigger_override(d.get("enabled_triggers"))
        cam_cfgs.append(
            CameraConfig(
                camera_id=cam_id,
                main_uri=uri,
                enabled=bool(d.get("enabled", True)),
                name=str(d.get("name") or cam_id).strip() or cam_id,
                enabled_triggers=None if override is None else frozenset(override),
            )
        )
    raw = {
        "node_id": getattr(settings, "node_id", ""),
        "cameras": [],
        "trigger": {
            "mode": settings.trigger_mode,
            "enabled": list(settings.enabled_triggers),
            "min_tracks": settings.min_tracks,
            "converge_dist_bh": settings.converge_dist_bh,
            "speed_thresh_bh": settings.speed_thresh_bh,
            "sustain_s": settings.sustain_s,
            "cooldown_s": settings.cooldown_s,
            "presence_min_people": settings.presence_min_people,
            "presence_sustain_s": settings.presence_sustain_s,
            "vif_iou_thresh": settings.vif_iou_thresh,
            "vif_sustain_s": settings.vif_sustain_s,
        },
        "record": {
            "clip_pre_s": settings.clip_pre_s,
            "clip_post_s": settings.clip_post_s,
        },
        "pipeline": {
            "infer_interval": settings.infer_interval,
            "conf_threshold": settings.conf_threshold,
            "live_source": True,
            "reconnect_s": settings.reconnect_s,
            "stream_silent_s": settings.stream_silent_s,
            "mux_width": settings.mux_width,
            "mux_height": settings.mux_height,
            "person_class_id": settings.person_class_id,
            "detector_model": settings.detector_model,
        },
    }
    cfg = app_config_from_dict(raw)
    cfg.cameras = cam_cfgs
    return cfg


def load_config(path: str | Path) -> AppConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"config file {path} must be a JSON object")
    return app_config_from_dict(raw)
