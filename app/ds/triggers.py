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

# Life-size cutouts / wall decals sit still. After this age they are furniture.
_STATIC_AGE_S = 5.0
_STICKY_TTL_S = 20.0
_STATIC_IOU = 0.4
_MOVE_BH = 0.2
# Do not fire person triggers until background boxes have been learned.
_WARMUP_S = 8.0


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


@dataclass(slots=True)
class StickyBox:
    cx: float
    cy: float
    w: float
    h: float
    first_ts: float
    last_ts: float


@dataclass
class CameraTriggerState:
    camera_id: str
    last_frame_ts: float = field(default_factory=time.monotonic)
    saw_frame: bool = False
    last_video_s: float | None = None
    warmup_from: float | None = None
    presence_since: float | None = None
    presence_last_hit: float | None = None
    converge_since: float | None = None
    converge_last_hit: float | None = None
    vif_since: float | None = None
    vif_last_hit: float | None = None
    last_fire: dict[str, float] = field(default_factory=dict)
    prev_centers: dict[int, tuple[float, float, float]] = field(default_factory=dict)
    sticky: list[StickyBox] = field(default_factory=list)

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
        self._cams = {c.camera_id: c for c in cameras}
        self.by_pad: dict[int, CameraTriggerState] = {}
        for idx, cam in enumerate(cameras):
            self.by_pad[idx] = CameraTriggerState(camera_id=cam.camera_id)

    def _allows(self, camera_id: str, kind: str) -> bool:
        cam = self._cams.get(camera_id)
        if cam is not None and cam.enabled_triggers is not None:
            return kind in cam.enabled_triggers
        return self.trigger.allows(kind)

    def _t(self, kind: str, key: str, fallback: float | int) -> float | int:
        return self.trigger.value(kind, key, fallback)

    def note_frame(self, pad_index: int, video_s: float | None = None) -> None:
        st = self.by_pad.get(pad_index)
        if st:
            now = time.monotonic()
            st.last_frame_ts = now
            st.saw_frame = True
            if st.warmup_from is None:
                st.warmup_from = now
            if video_s is not None and video_s >= 0:
                st.last_video_s = float(video_s)

    def check_stream_silent(self) -> None:
        now = time.monotonic()
        silent_s = float(
            self._t(
                "stream_silent",
                "stream_silent_s",
                self.app_cfg.pipeline.stream_silent_s,
            )
        )
        cooldown = float(
            self._t("stream_silent", "cooldown_s", self.trigger.cooldown_s)
        )
        for st in self.by_pad.values():
            if not self._allows(st.camera_id, "stream_silent"):
                continue
            if not st.saw_frame:
                continue
            if now - st.last_frame_ts < silent_s:
                continue
            if not st.cooled_down("stream_silent", cooldown, now):
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
        if st.warmup_from is None:
            st.warmup_from = now
        raw = [d for d in detections if d.h > 0 and d.w > 0]
        warming = (now - st.warmup_from) < _WARMUP_S
        people = self._live_people(st, raw, now, force_static=warming)
        if warming:
            return
        if self._allows(st.camera_id, "presence"):
            self._eval_presence(st, people, now, raw_n=len(raw))
        if self._allows(st.camera_id, "convergence"):
            self._eval_convergence(st, people, now)
        if self._allows(st.camera_id, "vif"):
            self._eval_vif(st, people, now)
        if people:
            st.prev_centers = {d.track_id: (d.cx, d.cy, now) for d in people}

    def _live_people(
        self,
        st: CameraTriggerState,
        people: list[Detection],
        now: float,
        *,
        force_static: bool = False,
    ) -> list[Detection]:
        """Drop boxes that have sat still (cutouts, posters, plants)."""
        unused = list(range(len(st.sticky)))
        live: list[Detection] = []
        seeded_ts = now - _STATIC_AGE_S
        for det in people:
            best_i = -1
            best_iou = 0.0
            for i in unused:
                box = st.sticky[i]
                iou = det.iou(
                    Detection(
                        track_id=-1,
                        cx=box.cx,
                        cy=box.cy,
                        w=box.w,
                        h=box.h,
                        conf=0.0,
                    )
                )
                if iou > best_iou:
                    best_iou = iou
                    best_i = i
            if best_i >= 0 and best_iou >= _STATIC_IOU:
                box = st.sticky[best_i]
                unused.remove(best_i)
                dist = math.hypot(det.cx - box.cx, det.cy - box.cy)
                moved = dist > _MOVE_BH * max(det.bh, box.h, 1.0)
                box.last_ts = now
                if moved:
                    box.cx, box.cy, box.w, box.h = det.cx, det.cy, det.w, det.h
                    box.first_ts = seeded_ts if force_static else now
                    if not force_static:
                        live.append(det)
                elif force_static:
                    box.first_ts = min(box.first_ts, seeded_ts)
                elif (now - box.first_ts) < _STATIC_AGE_S:
                    live.append(det)
            else:
                st.sticky.append(
                    StickyBox(
                        cx=det.cx,
                        cy=det.cy,
                        w=det.w,
                        h=det.h,
                        first_ts=seeded_ts if force_static else now,
                        last_ts=now,
                    )
                )
                if not force_static:
                    live.append(det)
        st.sticky = [b for b in st.sticky if (now - b.last_ts) < _STICKY_TTL_S]
        return live

    def _still_held(self, last_hit: float | None, now: float, hold_s: float) -> bool:
        return last_hit is not None and (now - last_hit) < hold_s

    def _miss_hold_s(self, sustain_s: float) -> float:
        # nvinfer skip frames have people=0. Hold only those batches plus a
        # couple of detector misses — not 0.4–2s of empty hallway.
        skip = max(0, int(self.app_cfg.pipeline.infer_interval) - 1)
        hold = (skip + 2) / 25.0
        cap = max(0.0, float(sustain_s) * 0.25)
        return min(hold, cap) if cap > 0 else hold

    def _eval_presence(
        self,
        st: CameraTriggerState,
        people: list[Detection],
        now: float,
        *,
        raw_n: int,
    ) -> None:
        need = int(
            self._t("presence", "presence_min_people", self.trigger.presence_min_people)
        )
        sustain = float(
            self._t("presence", "presence_sustain_s", self.trigger.presence_sustain_s)
        )
        cooldown = float(self._t("presence", "cooldown_s", self.trigger.cooldown_s))
        if len(people) >= need:
            st.presence_last_hit = now
            if st.presence_since is None:
                st.presence_since = now
                logger.info(
                    "presence arm camera=%s live=%s raw=%s need=%.1fs",
                    st.camera_id,
                    len(people),
                    raw_n,
                    sustain,
                )
            elif (now - st.presence_since) >= sustain:
                if st.cooled_down("presence", cooldown, now):
                    self._emit(
                        st,
                        trigger_type="presence",
                        evidence={
                            "people": len(people),
                            "people_raw": raw_n,
                            "static": max(0, raw_n - len(people)),
                            "max_conf": round(max(d.conf for d in people), 3),
                            "max_h": round(max(d.h for d in people), 1),
                        },
                    )
                st.presence_since = now
            return
        if self._still_held(st.presence_last_hit, now, self._miss_hold_s(sustain)):
            return
        st.presence_since = None

    def _eval_convergence(
        self, st: CameraTriggerState, people: list[Detection], now: float
    ) -> None:
        min_tracks = int(self._t("convergence", "min_tracks", self.trigger.min_tracks))
        converge_dist = float(
            self._t("convergence", "converge_dist_bh", self.trigger.converge_dist_bh)
        )
        speed_thresh = float(
            self._t("convergence", "speed_thresh_bh", self.trigger.speed_thresh_bh)
        )
        sustain = float(self._t("convergence", "sustain_s", self.trigger.sustain_s))
        cooldown = float(self._t("convergence", "cooldown_s", self.trigger.cooldown_s))
        if len(people) < min_tracks:
            if not self._still_held(
                st.converge_last_hit, now, self._miss_hold_s(sustain)
            ):
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
                if dist <= converge_dist:
                    close = True
                    pa = st.prev_centers.get(a.track_id)
                    pb = st.prev_centers.get(b.track_id)
                    if pa and pb:
                        prev_dist = math.hypot(pa[0] - pb[0], pa[1] - pb[1]) / (
                            (a.bh + b.bh) / 2.0
                        )
                        speed = (prev_dist - dist) / max(now - max(pa[2], pb[2]), 1e-3)
                        if speed >= speed_thresh * 0.05:
                            approaching = True

        if close and (approaching or self.trigger.mode == "convergence"):
            st.converge_last_hit = now
            if st.converge_since is None:
                st.converge_since = now
            elif (now - st.converge_since) >= sustain:
                if st.cooled_down("convergence", cooldown, now):
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
        elif not self._still_held(
            st.converge_last_hit, now, self._miss_hold_s(sustain)
        ):
            st.converge_since = None

    def _eval_vif(
        self, st: CameraTriggerState, people: list[Detection], now: float
    ) -> None:
        iou_thresh = float(
            self._t("vif", "vif_iou_thresh", self.trigger.vif_iou_thresh)
        )
        sustain = float(self._t("vif", "vif_sustain_s", self.trigger.vif_sustain_s))
        cooldown = float(self._t("vif", "cooldown_s", self.trigger.cooldown_s))
        if len(people) < 2:
            if not self._still_held(st.vif_last_hit, now, self._miss_hold_s(sustain)):
                st.vif_since = None
            return
        best_iou = 0.0
        for i in range(len(people)):
            for j in range(i + 1, len(people)):
                best_iou = max(best_iou, people[i].iou(people[j]))
        if best_iou >= iou_thresh:
            st.vif_last_hit = now
            if st.vif_since is None:
                st.vif_since = now
            elif (now - st.vif_since) >= sustain:
                if st.cooled_down("vif", cooldown, now):
                    self._emit(
                        st,
                        trigger_type="vif",
                        evidence={"people": len(people), "iou": round(best_iou, 3)},
                    )
                st.vif_since = now
        elif not self._still_held(st.vif_last_hit, now, self._miss_hold_s(sustain)):
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
        cam = self._cams.get(st.camera_id)
        payload = build_payload(
            camera_id=st.camera_id,
            camera_name=(cam.name if cam else "") or st.camera_id,
            camera_uri=(cam.main_uri if cam else "") or "",
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
            self.sink.send(payload)
        except Exception:
            logger.exception("failed to send trigger")
