"""Sticky / furniture filter: drop still cutouts and wall decals from person boxes."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.ds.triggers import Detection

# Life-size cutouts / wall decals sit still. After this age they are furniture.
STATIC_AGE_S = 5.0
STICKY_TTL_S = 20.0
STATIC_IOU = 0.4
MOVE_BH = 0.2
# Do not fire person triggers until background boxes have been learned.
WARMUP_S = 8.0


@dataclass(slots=True)
class StickyBox:
    cx: float
    cy: float
    w: float
    h: float
    first_ts: float
    last_ts: float


def filter_live_people(
    sticky: list[StickyBox],
    people: list[Detection],
    now: float,
    *,
    force_static: bool = False,
) -> list[Detection]:
    """Drop boxes that have sat still (cutouts, posters, plants). Mutates ``sticky``."""
    from app.ds.triggers import Detection as Det

    unused = list(range(len(sticky)))
    live: list[Det] = []
    seeded_ts = now - STATIC_AGE_S
    for det in people:
        best_i = -1
        best_iou = 0.0
        for i in unused:
            box = sticky[i]
            iou = det.iou(
                Det(
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
        if best_i >= 0 and best_iou >= STATIC_IOU:
            box = sticky[best_i]
            unused.remove(best_i)
            dist = math.hypot(det.cx - box.cx, det.cy - box.cy)
            moved = dist > MOVE_BH * max(det.bh, box.h, 1.0)
            box.last_ts = now
            if moved:
                box.cx, box.cy, box.w, box.h = det.cx, det.cy, det.w, det.h
                box.first_ts = seeded_ts if force_static else now
                if not force_static:
                    live.append(det)
            elif force_static:
                box.first_ts = min(box.first_ts, seeded_ts)
            elif (now - box.first_ts) < STATIC_AGE_S:
                live.append(det)
        else:
            sticky.append(
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
    sticky[:] = [b for b in sticky if (now - b.last_ts) < STICKY_TTL_S]
    return live
