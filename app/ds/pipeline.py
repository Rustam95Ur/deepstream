"""DeepStream Flow pipeline + metadata probe (stable facade)."""

from __future__ import annotations

from app.ds.pgie_config import write_pgie_config, write_source_config
from app.ds.pipeline_runner import run_pipeline
from app.ds.probe import bbox_xywh, build_probe, frame_video_seconds, obj_attr

__all__ = [
    "bbox_xywh",
    "build_probe",
    "frame_video_seconds",
    "obj_attr",
    "run_pipeline",
    "write_pgie_config",
    "write_source_config",
]

# Private aliases kept for any in-tree callers that used underscored names.
_obj_attr = obj_attr
_bbox_xywh = bbox_xywh
_frame_video_seconds = frame_video_seconds
