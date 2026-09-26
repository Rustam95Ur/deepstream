"""DeepStream batch metadata probe (person detections → TriggerEngine)."""

from __future__ import annotations

import logging
import os
from typing import Any

from app.ds.triggers import Detection, TriggerEngine

logger = logging.getLogger(__name__)


def obj_attr(obj: Any, *names: str, default=None):
    for name in names:
        if hasattr(obj, name):
            val = getattr(obj, name)
            if val is not None:
                return val
    return default


def bbox_xywh(obj: Any) -> tuple[float, float, float, float] | None:
    rect = obj_attr(obj, "rect_params", "rect", "bbox")
    if rect is not None:
        left = float(obj_attr(rect, "left", "x", default=0) or 0)
        top = float(obj_attr(rect, "top", "y", default=0) or 0)
        width = float(obj_attr(rect, "width", "w", default=0) or 0)
        height = float(obj_attr(rect, "height", "h", default=0) or 0)
        if width > 0 and height > 0:
            return left, top, width, height

    left = obj_attr(obj, "left", "x")
    top = obj_attr(obj, "top", "y")
    width = obj_attr(obj, "width", "w")
    height = obj_attr(obj, "height", "h")
    if None not in (left, top, width, height):
        w, h = float(width), float(height)
        if w > 0 and h > 0:
            return float(left), float(top), w, h
    return None


def frame_video_seconds(frame_meta: Any) -> float | None:
    """Best-effort media time for file/inbox sources (PTS or frame_num)."""
    # Prefer buf_pts (media clock). Do NOT use ntp_timestamp — that is wall-clock.
    pts = obj_attr(frame_meta, "buf_pts", "bufPts")
    if pts is not None:
        try:
            raw = float(pts)
        except (TypeError, ValueError):
            raw = -1.0
        if raw >= 0:
            # GStreamer/DeepStream PTS is usually nanoseconds.
            if raw >= 1e11:
                return raw / 1e9
            if raw >= 1e8:
                return raw / 1e6
            return raw
    frame_num = obj_attr(frame_meta, "frame_num", "frameNum")
    if frame_num is not None:
        try:
            return max(0.0, float(frame_num) / 25.0)
        except (TypeError, ValueError):
            return None
    return None


def build_probe(
    engine: TriggerEngine,
    person_class_id: int,
    conf_threshold: float,
    *,
    on_frame=None,
):
    from pyservicemaker import BatchMetadataOperator, Probe

    class IncidentProbe(BatchMetadataOperator):
        def handle_metadata(self, batch_meta):
            if not hasattr(self, "_frames"):
                self._frames = 0
            for frame_meta in batch_meta.frame_items:
                pad_index = int(
                    obj_attr(frame_meta, "pad_index", "padIndex", default=0) or 0
                )
                video_s = frame_video_seconds(frame_meta)
                if video_s is None:
                    fps = float(os.environ.get("DEEPSTREAM_INBOX_FPS", "25") or 25)
                    video_s = max(0.0, float(self._frames) / max(1.0, fps))
                engine.note_frame(pad_index, video_s=video_s)
                detections: list[Detection] = []
                for object_meta in frame_meta.object_items:
                    class_id = int(
                        obj_attr(object_meta, "class_id", "classId", default=-1)
                    )
                    if class_id != person_class_id:
                        continue
                    conf = float(
                        obj_attr(object_meta, "confidence", "conf", default=1.0) or 1.0
                    )
                    if conf < conf_threshold:
                        continue
                    box = bbox_xywh(object_meta)
                    if not box:
                        continue
                    left, top, width, height = box
                    track_id = int(
                        obj_attr(
                            object_meta,
                            "object_id",
                            "tracker_id",
                            "objectId",
                            default=len(detections),
                        )
                        or len(detections)
                    )
                    detections.append(
                        Detection(
                            track_id=track_id,
                            cx=left + width / 2.0,
                            cy=top + height / 2.0,
                            w=width,
                            h=height,
                            conf=conf,
                        )
                    )
                engine.process_detections(pad_index, detections)
                self._frames += 1
                if on_frame is not None:
                    try:
                        on_frame(self._frames)
                    except Exception:
                        logger.exception("on_frame callback failed")
                if self._frames == 1 or self._frames % 250 == 0:
                    logger.info(
                        "probe frames=%s pad=%s people=%s",
                        self._frames,
                        pad_index,
                        len(detections),
                    )

    return Probe("nexus_deepstream_incident", IncidentProbe())
