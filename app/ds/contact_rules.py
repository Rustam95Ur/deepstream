"""Contact rules: the "vif" (fight / bullying) first-line trigger.

Per camera. A *contact* = two tracked kids whose boxes overlap (IoU >=
``iou_on``), gaps up to ``gap_s`` bridged, lasting >= ``min_contact_s``. A
contact fires once when, during it (from 0.5 s before it starts to 0.5 s after
it ends), for at least one of the two kids, in some 1-second window:

    std of the hip-shoulder-elbow angle   >= armt_std
    std of the hip-knee-ankle angle       >= knee_std
    std of the shoulder-elbow-wrist angle >= elbow_std

(each condition may be met by either kid, in any window), and the mean IoU of
the contact >= ``iou_mean``. "std" is averaged over the left and right side; an
angle is used only if its 3 keypoints have score >= ``joint_conf``.

While the contact lasts it fires as soon as all conditions are *measured* and
met. A condition that was never measured (joints never visible for a whole
window, or no pose model) counts as met when the contact ends: recall first,
the VLM decides.

Fitted on 80 labelled school clips (person-level labels): all 45 incidents
whose two kids' boxes touch were caught, 36% of ordinary contacts pass. The
angle thresholds were measured with RTMO-m skeletons and should be re-fitted
for the pose model in production (``on_close`` gives every contact's values).
Times are seconds of the camera's own clock.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from collections.abc import Iterable, Sequence

# COCO-17 keypoint indices
L_SH, R_SH, L_EL, R_EL, L_WR, R_WR = 5, 6, 7, 8, 9, 10
L_HIP, R_HIP, L_KN, R_KN, L_AN, R_AN = 11, 12, 13, 14, 15, 16
TRIPLES = {
    "armt": ((L_HIP, L_SH, L_EL), (R_HIP, R_SH, R_EL)),
    "knee": ((L_HIP, L_KN, L_AN), (R_HIP, R_KN, R_AN)),
    "elbow": ((L_SH, L_EL, L_WR), (R_SH, R_EL, R_WR)),
}
FEATS = ("armt_std", "knee_std", "elbow_std")
NEG_INF = float("-inf")

# Fitted with this engine on the 80 labelled clips (RTMO-m skeletons), 5% below
# the weakest incident: 45/45 caught, 36% of ordinary contacts pass; with each
# clip held out of the fit, 42/45 of the held-out incidents are caught.
DEFAULTS = {
    "vif_iou_thresh": 0.05,  # contact: min IoU
    "vif_sustain_s": 0.5,  # contact: min length (s)
    "armt_std": 10.183,
    "knee_std": 7.6658,
    "elbow_std": 27.1699,
    "iou_mean": 0.0565,
    "joint_conf": 0.3,
}

Box = tuple[float, float, float, float]  # x0, y0, x1, y1
Keypoints = Sequence[tuple[float, float, float]]  # 17 x (x, y, score)


def iou(a: Box, b: Box) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def angle(k: Keypoints, a: int, b: int, c: int, jc: float) -> float:
    if k[a][2] < jc or k[b][2] < jc or k[c][2] < jc:
        return math.nan
    v1 = (k[a][0] - k[b][0], k[a][1] - k[b][1])
    v2 = (k[c][0] - k[b][0], k[c][1] - k[b][1])
    n1, n2 = math.hypot(*v1), math.hypot(*v2)
    if n1 < 1e-6 or n2 < 1e-6:
        return math.nan
    cos = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def _std(v: list[float]) -> float:
    m = sum(v) / len(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / len(v))


def met(value: float, thr: float) -> bool:
    """-inf = never measured -> counts as met (only used when the contact ends)"""
    return value >= thr or value == NEG_INF


@dataclass(slots=True)
class Person:
    track_id: int
    box: Box
    kpts: Keypoints | None = None


@dataclass(slots=True)
class ContactEvent:
    a: int
    b: int
    t: float
    start: float
    box_a: Box
    box_b: Box
    values: dict
    late: bool  # fired at contact end because something was never measured

    def evidence(self) -> dict:
        return {
            "rule": "contact",
            "pair": [self.a, self.b],
            "box_a": [round(v, 1) for v in self.box_a],
            "box_b": [round(v, 1) for v in self.box_b],
            "contact_start_s": round(self.start, 2),
            "contact_len_s": round(self.t - self.start, 2),
            "late": self.late,
            **{
                k: (None if v == NEG_INF else round(v, 3))
                for k, v in self.values.items()
            },
        }


@dataclass(slots=True)
class _Pair:
    start: float
    last: float
    hits: int = 0
    iou_sum: float = 0.0
    fired: bool = False
    best: dict = field(default_factory=lambda: {f: NEG_INF for f in FEATS})


class ContactRules:
    """One per camera. ``update(t, people)`` once per frame, t in seconds, increasing."""

    def __init__(
        self,
        thr: dict | None = None,
        *,
        frame_h: float = 1080.0,
        win_s: float = 1.0,
        step_s: float = 0.5,
        min_present: float = 0.8,
        pre_post_s: float = 0.5,
        gap_s: float = 0.5,
        on_close=None,
    ):
        self.thr = {**DEFAULTS, **(thr or {})}
        # calibration hook: on_close(pair, start_s, end_s, values) for every contact
        self.on_close = on_close
        self._args = dict(
            frame_h=frame_h,
            win_s=win_s,
            step_s=step_s,
            min_present=min_present,
            pre_post_s=pre_post_s,
            gap_s=gap_s,
            on_close=on_close,
        )
        # rules were measured at 1080p with a 40 px minimum skeleton height
        self.min_h = 40.0 * frame_h / 1080.0
        self.win_s, self.step_s, self.min_present = win_s, step_s, min_present
        self.pre_post_s, self.gap_s = pre_post_s, gap_s
        self.hist: dict[int, deque] = defaultdict(deque)  # tid -> (t, angles)
        self.wins: dict[int, deque] = defaultdict(lambda: deque(maxlen=128))
        self.last_win: dict[int, float] = {}
        self.pairs: dict[tuple[int, int], _Pair] = {}
        self.boxes: dict[int, Box] = {}
        self.last_t: float | None = None
        self.dt = 0.04  # frame interval estimate

    def reset(self) -> None:
        self.__init__(self.thr, **self._args)

    # ------------------------------------------------------------------ kids
    def _kid(self, t: float, p: Person) -> None:
        h = self.hist[p.track_id]
        if (
            p.kpts is not None
            and len(p.kpts) >= 17
            and p.box[3] - p.box[1] >= self.min_h
        ):
            jc = self.thr["joint_conf"]
            ang = {
                key: tuple(angle(p.kpts, *tri, jc) for tri in sides)
                for key, sides in TRIPLES.items()
            }
            h.append((t, ang))
        while h and h[0][0] < t - self.win_s - 1e-6:
            h.popleft()
        if t - self.last_win.get(p.track_id, -1e9) < self.step_s - 1e-6:
            return
        expected = self.win_s / max(self.dt, 1e-3)
        if len(h) < self.min_present * expected:
            return
        self.last_win[p.track_id] = t
        out = {}
        for key in TRIPLES:
            sds = []
            for side in (0, 1):
                v = [x[1][key][side] for x in h if not math.isnan(x[1][key][side])]
                if v:
                    sds.append(_std(v))
            out[f"{key}_std"] = sum(sds) / len(sds) if sds else math.nan
        self.wins[p.track_id].append((t, out))

    # ------------------------------------------------------------------ frame
    def update(self, t: float, people: Iterable[Person]) -> list[ContactEvent]:
        if self.last_t is not None:
            if t < self.last_t:  # clock went back (stream restart)
                self.reset()
            elif t > self.last_t:
                self.dt = 0.9 * self.dt + 0.1 * min(t - self.last_t, 0.5)
        self.last_t = t
        people = list(people)
        for p in people:
            self._kid(t, p)
            self.boxes[p.track_id] = p.box
        events: list[ContactEvent] = []
        iou_on = self.thr["vif_iou_thresh"]
        for i in range(len(people)):
            for j in range(i + 1, len(people)):
                v = iou(people[i].box, people[j].box)
                if v < iou_on:
                    continue
                key = tuple(sorted((people[i].track_id, people[j].track_id)))
                pr = self.pairs.get(key)
                if pr is None or t - pr.last > self.gap_s:
                    if pr is not None:
                        ev = self._close(key, pr, t)
                        if ev:
                            events.append(ev)
                    pr = self.pairs[key] = _Pair(start=t, last=t)
                pr.last = t
                pr.hits += 1
                pr.iou_sum += v
        min_len = self.thr["vif_sustain_s"]
        for key, pr in list(self.pairs.items()):
            if pr.last - pr.start >= min_len and not pr.fired:
                vals = self._values(key, pr)
                if all(vals[f] >= self.thr[f] for f in (*FEATS, "iou_mean")):
                    events.append(self._event(key, pr, t, vals, late=False))
            if t - pr.last > self.gap_s:
                ev = self._close(key, pr, t)
                if ev:
                    events.append(ev)
                del self.pairs[key]
        # forget kids not seen for a while
        for tid in [k for k, h in self.hist.items() if h and h[-1][0] < t - 10]:
            self.hist.pop(tid, None)
            self.wins.pop(tid, None)
            self.last_win.pop(tid, None)
            self.boxes.pop(tid, None)
        return events

    def _values(self, key, pr: _Pair) -> dict:
        lo, hi = pr.start - self.pre_post_s, pr.last + self.pre_post_s
        for tid in key:
            for end, v in self.wins.get(tid, ()):
                if end >= lo and end - self.win_s <= hi:
                    for f in FEATS:
                        if not math.isnan(v[f]):
                            pr.best[f] = max(pr.best[f], v[f])
        return {**pr.best, "iou_mean": pr.iou_sum / max(pr.hits, 1)}

    def _event(
        self, key, pr: _Pair, t: float, vals: dict, *, late: bool
    ) -> ContactEvent:
        pr.fired = True
        return ContactEvent(
            key[0],
            key[1],
            t,
            pr.start,
            self.boxes.get(key[0], (0, 0, 0, 0)),
            self.boxes.get(key[1], (0, 0, 0, 0)),
            vals,
            late,
        )

    def _close(self, key, pr: _Pair, t: float) -> ContactEvent | None:
        if pr.last - pr.start < self.thr["vif_sustain_s"]:
            return None
        vals = self._values(key, pr)
        if self.on_close is not None:
            self.on_close(key, pr.start, pr.last, dict(vals))
        if pr.fired:
            return None
        if all(met(vals[f], self.thr[f]) for f in (*FEATS, "iou_mean")):
            return self._event(key, pr, t, vals, late=True)
        return None
