"""Contact rules (vif trigger), pose keypoint mapping and trigger wiring.

Pure Python, no GPU / DeepStream needed:  python -m pytest tests/
"""

from __future__ import annotations

import math
import time

import pytest

from app.ds.contact_rules import DEFAULTS, ContactRules, Person

FPS = 25.0


def body(hx, hy, h, arm_r=(20.0, 150.0), arm_l=(20.0, 150.0), facing=1):
    """17 COCO keypoints (x, y, 0.9) of a stick figure. arm = (theta, elbow) degrees."""
    k = [(0.0, 0.0)] * 17
    k = list(k)
    k[0] = (hx, hy - 0.42 * h)
    for i in (1, 2, 3, 4):
        k[i] = (hx, hy - 0.43 * h)
    k[5], k[6] = (hx - 0.11 * h, hy - 0.30 * h), (hx + 0.11 * h, hy - 0.30 * h)
    k[11], k[12] = (hx - 0.08 * h, hy), (hx + 0.08 * h, hy)
    k[13], k[14] = (hx - 0.08 * h, hy + 0.25 * h), (hx + 0.08 * h, hy + 0.25 * h)
    k[15], k[16] = (hx - 0.08 * h, hy + 0.48 * h), (hx + 0.08 * h, hy + 0.48 * h)
    for (th, eb), sh, el, wr in ((arm_l, 5, 7, 9), (arm_r, 6, 8, 10)):
        a1 = math.radians(th)
        k[el] = (
            k[sh][0] + 0.17 * h * math.sin(a1) * facing,
            k[sh][1] + 0.17 * h * math.cos(a1),
        )
        a2 = a1 + math.radians(180 - eb)
        k[wr] = (
            k[el][0] + 0.16 * h * math.sin(a2) * facing,
            k[el][1] + 0.16 * h * math.cos(a2),
        )
    return [(x, y, 0.9) for x, y in k]


def person(tid, kp, conf=None):
    xs, ys = [p[0] for p in kp], [p[1] for p in kp]
    box = (min(xs) - 8, min(ys) - 14, max(xs) + 8, max(ys) + 6)
    if conf is not None:
        kp = [(x, y, conf) for x, y, _ in kp]
    return Person(tid, box, kp)


def fight_frame(t, conf=None):
    """kid 1 throws 3 fast punches at kid 2 (2.2, 2.9, 3.6 s); kid 3 walks past far away"""
    punch = max([max(0.0, 1 - abs(t - c) / 0.1) for c in (2.2, 2.9, 3.6)])
    p1 = body(270, 200, 150, arm_r=(30 + 60 * punch, 80 + 95 * punch), facing=1)
    sway = 6 * math.sin(2 * math.pi * 1.5 * t)
    p2 = body(335 + sway, 200, 150, facing=-1)
    p3 = body(560 - 20 * t, 210, 140)
    return [person(1, p1, conf), person(2, p2, conf), person(3, p3, conf)]


def run(engine, frame_fn, secs=6.0, **kw):
    events = []
    n = int(secs * FPS)
    for i in range(n):
        events += engine.update(i / FPS, frame_fn(i / FPS, **kw))
    events += engine.update(secs + 5.0, [])  # end of stream closes contacts
    return events


# synthetic one-arm punch: arm-torso std ~8.5, elbow std ~13.5 (left/right averaged)
SYNTH = {"armt_std": 8.0, "knee_std": 0.0, "elbow_std": 12.0, "iou_mean": 0.05}


def test_punching_pair_fires_once_and_passer_by_never():
    ev = run(ContactRules(SYNTH, frame_h=360), fight_frame)
    assert [(e.a, e.b) for e in ev] == [(1, 2)]
    assert not ev[0].late
    evd = ev[0].evidence()
    assert evd["pair"] == [1, 2] and evd["rule"] == "contact"


def test_impossible_thresholds_never_fire():
    strict = {"armt_std": 1e9, "knee_std": 1e9, "elbow_std": 1e9, "iou_mean": 0.0}
    assert run(ContactRules(strict, frame_h=360), fight_frame) == []


def test_no_visible_joints_fires_late_at_contact_end():
    ev = run(ContactRules(SYNTH, frame_h=360), fight_frame, conf=0.0)
    assert len(ev) == 1 and ev[0].late
    assert ev[0].evidence()["armt_std"] is None


def test_no_pose_model_still_fires_late():
    def boxes_only(t):
        return [Person(p.track_id, p.box, None) for p in fight_frame(t)]

    ev = run(ContactRules(SYNTH, frame_h=360), boxes_only)
    assert len(ev) == 1 and ev[0].late


def test_short_contact_does_not_fire():
    def brush(t):
        x = 100 + 400 * t  # kid 2 runs past kid 1 in ~0.2 s of overlap
        return [person(1, body(300, 200, 150)), person(2, body(x, 200, 150))]

    assert run(ContactRules(SYNTH, frame_h=360), brush, secs=1.0) == []


def test_clock_going_back_resets():
    eng = ContactRules(SYNTH, frame_h=360)
    for i in range(50):
        eng.update(i / FPS, fight_frame(i / FPS))
    assert eng.pairs
    eng.update(0.0, [])
    assert not eng.pairs and not eng.hist


def test_defaults_match_trigger_profile():
    from app.trigger_thresholds import DEFAULT_THRESHOLD_PROFILES

    vif = DEFAULT_THRESHOLD_PROFILES["vif"]
    for key, value in DEFAULTS.items():
        assert vif[key] == pytest.approx(value)


# ---------------------------------------------------------------- probe mapping
class _Layer:
    def __init__(self, values):
        import numpy as np

        self.arr = np.asarray(values, dtype=np.float32).reshape(1, 17, 3)

    def __dlpack__(self, *a, **k):
        return self.arr.__dlpack__(*a, **k)

    def __dlpack_device__(self):
        return self.arr.__dlpack_device__()


class _TensorOut:
    def __init__(self, layer):
        self.layer = layer

    def get_layers(self):
        return {"keypoints": self.layer}


class _UserMeta:
    def __init__(self, layer):
        self.layer = layer

    def as_tensor_output(self):
        return _TensorOut(self.layer)


class _Obj:
    def __init__(self, layer):
        self.tensor_items = [_UserMeta(layer)]


def test_probe_maps_network_keypoints_back_to_frame():
    pytest.importorskip("numpy")
    from app.ds.pgie_config import POSE_INPUT_H, POSE_INPUT_W
    from app.ds.probe import object_keypoints

    left, top, w, h = 400.0, 120.0, 70.0, 210.0
    truth = [(left + 5 + 3 * j, top + 10 + 11 * j, 0.8) for j in range(17)]
    s = min(POSE_INPUT_W / w, POSE_INPUT_H / h)
    px, py = (POSE_INPUT_W - w * s) / 2, (POSE_INPUT_H - h * s) / 2
    net = [v for x, y, c in truth for v in ((x - left) * s + px, (y - top) * s + py, c)]
    got = object_keypoints(_Obj(_Layer(net)), left, top, w, h)
    assert got is not None
    for (gx, gy, gc), (tx, ty, tc) in zip(got, truth):
        assert gx == pytest.approx(tx, abs=1e-3) and gy == pytest.approx(ty, abs=1e-3)
        assert gc == pytest.approx(tc)


def test_probe_without_tensor_meta_gives_none():
    from app.ds.probe import object_keypoints

    assert object_keypoints(object(), 0, 0, 10, 10) is None


# ---------------------------------------------------------------- trigger wiring
class _Sink:
    source_video = None

    def __init__(self):
        self.payloads = []

    def send(self, payload):
        self.payloads.append(payload)


def test_trigger_engine_emits_vif_with_pair_evidence():
    from app.ds.config import app_config_from_dict
    from app.ds.triggers import Detection, TriggerEngine

    cfg = app_config_from_dict(
        {
            "cameras": [{"id": "cam1", "main_uri": "rtsp://x/1"}],
            "trigger": {"enabled": ["vif"], "by_type": {"vif": SYNTH}},
            "pipeline": {"mux_height": 360},
        }
    )
    sink = _Sink()
    eng = TriggerEngine(cfg, cfg.cameras, sink)
    eng.note_frame(0, video_s=0.0)
    eng.by_pad[0].warmup_from = time.monotonic() - 100  # skip the warm-up
    for i in range(int(6 * FPS)):
        t = i / FPS
        eng.note_frame(0, video_s=t)
        dets = []
        for p in fight_frame(t):
            x0, y0, x1, y1 = p.box
            dets.append(
                Detection(
                    p.track_id,
                    (x0 + x1) / 2,
                    (y0 + y1) / 2,
                    x1 - x0,
                    y1 - y0,
                    0.9,
                    kpts=list(p.kpts),
                )
            )
        eng.process_detections(0, dets)
    vif = [p for p in sink.payloads if p.get("trigger_type") == "vif"]
    assert len(vif) == 1
    ev = vif[0]["evidence"]
    assert ev["pair"] == [1, 2] and ev["rule"] == "contact"
    assert vif[0]["pre_s"] >= cfg.record.clip_pre_s
    # clip starts 5 s before the contact began
    assert vif[0]["pre_s"] == pytest.approx(ev["contact_len_s"] + 5.0, abs=0.05)
