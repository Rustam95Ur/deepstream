"""Person-based triggers: presence / convergence / vif (IoU proxy)."""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any

from app.ds.config import AppConfig, CameraConfig, TriggerConfig
from app.ds.payload import build_payload

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Detection:
    track_id: int
    cx: float
    cy: float
    w: float
    h: float
    conf: float

    @property
    def bh(self) -> float:
        return max(self.h, 1.0)

    def iou(self, other: Detection) -> float:
        x1 = max(self.cx - self.w / 2, other.cx - other.w / 2)
        y1 = max(self.cy - self.h / 2, other.cy - other.h / 2)
        x2 = min(self.cx + self.w / 2, other.cx + other.w / 2)
        y2 = min(self.cy + self.h / 2, other.cy + other.h / 2)
        iw = max(0.0, x2 - x1)
        ih = max(0.0, y2 - y1)
        inter = iw * ih
        if inter <= 0:
            return 0.0
        union = self.w * self.h + other.w * other.h - inter
        return inter / union if union > 0 else 0.0

    def dist_bh(self, other: Detection) -> float:
        dx = self.cx - other.cx
        dy = self.cy - other.cy
        dist = math.hypot(dx, dy)
        scale = (self.bh + other.bh) / 2.0
        return dist / scale


@dataclass
class CameraTriggerState:
    camera_id: str
    last_frame_ts: float = field(default_factory=time.monotonic)
    saw_frame: bool = False
    last_video_s: float | None = None
    presence_since: float | None = None
    converge_since: float | None = None
    vif_since: float | None = None
    last_fire: dict[str, float] = field(default_factory=dict)
    prev_centers: dict[int, tuple[float, float, float]] = field(default_factory=dict)

    def cooled_down(self, trigger_type: str, cooldown_s: float, now: float) -> bool:
        last = self.last_fire.get(trigger_type)
        return last is None or (now - last) >= cooldown_s

    def mark_fired(self, trigger_type: str, now: float) -> None:
        self.last_fire[trigger_type] = now


class TriggerEngine:
    def __init__(
        self,
        app_cfg: AppConfig,
        cameras: list[CameraConfig],
        sink: Any,
    ) -> None:
        self.app_cfg = app_cfg
        self.trigger: TriggerConfig = app_cfg.trigger
        self.sink = sink
        self.by_pad: dict[int, CameraTriggerState] = {}
        for idx, cam in enumerate(cameras):
            self.by_pad[idx] = CameraTriggerState(camera_id=cam.camera_id)

    def note_frame(self, pad_index: int, video_s: float | None = None) -> None:
        st = self.by_pad.get(pad_index)
        if st:
            st.last_frame_ts = time.monotonic()
            st.saw_frame = True
            if video_s is not None and video_s >= 0:
                st.last_video_s = float(video_s)

    def check_stream_silent(self) -> None:
        if not self.trigger.allows("stream_silent"):
            return
        now = time.monotonic()
        silent_s = self.app_cfg.pipeline.stream_silent_s
        for st in self.by_pad.values():
            if not st.saw_frame:
                continue
            if now - st.last_frame_ts < silent_s:
                continue
            if not st.cooled_down("stream_silent", self.trigger.cooldown_s, now):
                continue
            self._emit(
                st,
                trigger_type="stream_silent",
                category="error",
                evidence={"silent_for_s": round(now - st.last_frame_ts, 1)},
            )
            st.last_frame_ts = now

    def process_detections(self, pad_index: int, detections: list[Detection]) -> None:
        st = self.by_pad.get(pad_index)
        if not st:
            return
        now = time.monotonic()
        st.last_frame_ts = now
        st.saw_frame = True
        people = [d for d in detections if d.h > 0 and d.w > 0]
        if self.trigger.allows("presence"):
            self._eval_presence(st, people, now)
        if self.trigger.allows("convergence"):
            self._eval_convergence(st, people, now)
        if self.trigger.allows("vif"):
            self._eval_vif(st, people, now)
        st.prev_centers = {d.track_id: (d.cx, d.cy, now) for d in people}

    def _eval_presence(
        self, st: CameraTriggerState, people: list[Detection], now: float
    ) -> None:
        need = self.trigger.presence_min_people
        if len(people) >= need:
            if st.presence_since is None:
                st.presence_since = now
            elif (now - st.presence_since) >= self.trigger.presence_sustain_s:
                if st.cooled_down("presence", self.trigger.cooldown_s, now):
                    self._emit(
                        st,
                        trigger_type="presence",
                        evidence={"people": len(people)},
                    )
                st.presence_since = now
        else:
            st.presence_since = None

    def _eval_convergence(
        self, st: CameraTriggerState, people: list[Detection], now: float
    ) -> None:
        if len(people) < self.trigger.min_tracks:
            st.converge_since = None
            return

        close = False
        approaching = False
        best_dist = 1e9
        for i in range(len(people)):
            for j in range(i + 1, len(people)):
                a, b = people[i], people[j]
                dist = a.dist_bh(b)
                best_dist = min(best_dist, dist)
                if dist <= self.trigger.converge_dist_bh:
                    close = True
                    pa = st.prev_centers.get(a.track_id)
                    pb = st.prev_centers.get(b.track_id)
                    if pa and pb:
                        prev_dist = math.hypot(pa[0] - pb[0], pa[1] - pb[1]) / (
                            (a.bh + b.bh) / 2.0
                        )
                        speed = (prev_dist - dist) / max(now - max(pa[2], pb[2]), 1e-3)
                        if speed >= self.trigger.speed_thresh_bh * 0.05:
                            approaching = True

        if close and (approaching or self.trigger.mode == "convergence"):
            if st.converge_since is None:
                st.converge_since = now
            elif (now - st.converge_since) >= self.trigger.sustain_s:
                if st.cooled_down("convergence", self.trigger.cooldown_s, now):
                    self._emit(
                        st,
                        trigger_type="convergence",
                        evidence={
                            "people": len(people),
                            "min_dist_bh": round(best_dist, 3),
                            "approaching": approaching,
                        },
                    )
                st.converge_since = now
        else:
            st.converge_since = None

    def _eval_vif(
        self, st: CameraTriggerState, people: list[Detection], now: float
    ) -> None:
        if len(people) < 2:
            st.vif_since = None
            return
        best_iou = 0.0
        for i in range(len(people)):
            for j in range(i + 1, len(people)):
                best_iou = max(best_iou, people[i].iou(people[j]))
        if best_iou >= self.trigger.vif_iou_thresh:
            if st.vif_since is None:
                st.vif_since = now
            elif (now - st.vif_since) >= self.trigger.vif_sustain_s:
                if st.cooled_down("vif", self.trigger.cooldown_s, now):
                    self._emit(
                        st,
                        trigger_type="vif",
                        evidence={"people": len(people), "iou": round(best_iou, 3)},
                    )
                st.vif_since = now
        else:
            st.vif_since = None

    def _emit(
        self,
        st: CameraTriggerState,
        *,
        trigger_type: str,
        evidence: dict[str, Any],
        category: str = "incident",
    ) -> None:
        now = time.monotonic()
        payload = build_payload(
            camera_id=st.camera_id,
            trigger_type=trigger_type,
            pre_s=self.app_cfg.record.clip_pre_s,
            post_s=self.app_cfg.record.clip_post_s,
            evidence=evidence,
            category=category,
            source_video=getattr(self.sink, "source_video", None),
            source_offset_s=st.last_video_s,
            node_id=self.app_cfg.node_id,
        )
        st.mark_fired(trigger_type, now)
        logger.warning(
            "TRIGGER %s camera=%s evidence=%s",
            trigger_type,
            st.camera_id,
            evidence,
        )
        try:
            from app.history import record_trigger

            record_trigger(payload)
        except Exception:
            logger.exception("failed to persist trigger history")
        try:
            self.sink.send(payload)
        except Exception:
            logger.exception("failed to send trigger")
