"""DeepStream PGIE (nvinfer) and nvmultiurisrcbin YAML writers."""

from __future__ import annotations

import logging
from pathlib import Path

from app.ds.config import CameraConfig
from app.ds.rtsp import sanitize_rtsp_url
from app.runtime_env import get_runtime_env
from app.settings import normalize_detector_model

logger = logging.getLogger(__name__)


def write_pgie_config(
    dest: Path,
    *,
    batch_size: int,
    infer_interval: int,
    conf_threshold: float,
    detector_model: str = "peoplenet",
) -> Path:
    """nvinfer INI for NVIDIA TAO PeopleNet (ONNX, built-in DetectNet_v2 parser).

    Classes: 0 person, 1 bag, 2 face -> ``person_class_id`` stays 0.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    requested = (detector_model or "").strip().lower()
    model = normalize_detector_model(detector_model)
    if requested and requested != model:
        logger.warning(
            "detector_model=%s is not wired, using %s", requested, model
        )

    model_dir = (get_runtime_env().model_dir / "peoplenet").resolve()
    onnx = model_dir / "resnet34_peoplenet.onnx"
    labels = model_dir / "labels.txt"
    # nvinfer's own engine naming; next to the ONNX so it is reused across restarts
    engine = model_dir / f"resnet34_peoplenet.onnx_b{batch_size}_gpu0_fp16.engine"
    for f in (onnx, labels):
        if not f.is_file():
            raise FileNotFoundError(
                f"PeopleNet missing: {f}. Run models/peoplenet/prepare.sh"
            )

    # nvinfer `interval` = batches to SKIP (0 = every frame). Node setting is
    # "every Nth frame" (1 = every frame), so skip = N - 1. The tracker fills
    # the skipped frames.
    skip = max(0, int(infer_interval) - 1)
    text = f"""[property]
gpu-id=0
net-scale-factor=0.00392156862745098
offsets=0;0;0
model-color-format=0
onnx-file={onnx.as_posix()}
model-engine-file={engine.as_posix()}
labelfile-path={labels.as_posix()}
infer-dims=3;544;960
batch-size={batch_size}
network-mode=2
num-detected-classes=3
interval={skip}
gie-unique-id=1
process-mode=1
network-type=0
cluster-mode=2
output-blob-names=output_bbox/BiasAdd:0;output_cov/Sigmoid:0

[class-attrs-all]
pre-cluster-threshold=0.4
nms-iou-threshold=0.5
topk=100

[class-attrs-0]
pre-cluster-threshold={conf_threshold}
nms-iou-threshold=0.5
topk=100
"""
    if dest.suffix.lower() in (".yml", ".yaml"):
        dest = dest.with_suffix(".txt")
    dest.write_text(text, encoding="utf-8")
    return dest


POSE_INPUT_W = 192
POSE_INPUT_H = 256
POSE_OUTPUT_LAYER = "keypoints"


def pose_model_path() -> Path:
    return (get_runtime_env().model_dir / "rtmpose" / "rtmpose_kpts.onnx").resolve()


def write_pose_config(
    dest: Path,
    *,
    batch_size: int,
    min_object_height: int = 27,
    person_class_id: int = 0,
) -> Path | None:
    """Secondary nvinfer (SGIE): RTMPose-m on every tracked person crop.

    The ONNX already decodes SimCC (models/rtmpose/add_decode.py), so the only
    output is ``keypoints`` (N x 17 x 3: x, y in 192x256 network pixels, score),
    attached as tensor meta to each object. The crop keeps the aspect ratio with
    symmetric padding; app/ds/probe.py maps the points back to the frame.
    ``batch_size`` must be the streammux max batch: nvinfer stores the engine
    as ``{onnx}_b{batch}_gpu0_fp16.engine`` and will not load a different one.
    Returns None (pose disabled, rules fall back to contact-only) if the model
    is missing.
    """
    onnx = pose_model_path()
    if not onnx.is_file():
        return None
    engine = onnx.parent / f"{onnx.name}_b{batch_size}_gpu0_fp16.engine"
    # Preprocessing as rtmlib feeds RTMPose: BGR, mean subtracted per channel,
    # one scale for all channels (std ~57.6; nvinfer has a single scale factor).
    text = f"""[property]
gpu-id=0
net-scale-factor=0.017352
offsets=123.675;116.28;103.53
model-color-format=1
onnx-file={onnx.as_posix()}
model-engine-file={engine.as_posix()}
infer-dims=3;{POSE_INPUT_H};{POSE_INPUT_W}
batch-size={batch_size}
network-mode=2
gie-unique-id=2
process-mode=2
operate-on-gie-id=1
operate-on-class-ids={person_class_id}
network-type=100
output-tensor-meta=1
output-blob-names={POSE_OUTPUT_LAYER}
maintain-aspect-ratio=1
symmetric-padding=1
input-object-min-height={int(min_object_height)}
classifier-async-mode=0
"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    return dest


def _yaml_quote(value: str) -> str:
    return '"' + (value or "").replace("\\", "\\\\").replace('"', '\\"') + '"'


def write_source_config(
    dest: Path,
    cameras: list[CameraConfig],
    *,
    live_source: bool,
    width: int,
    height: int,
    drop_pipeline_eos: bool | None = None,
    max_batch_size: int | None = None,
    reconnect_s: float = 10.0,
) -> Path:
    """nvmultiurisrcbin YAML — RTSP uses TCP (protocol=4); file:// for inbox tests."""
    lines = [
        "source-list:",
    ]
    for cam in cameras:
        uri = sanitize_rtsp_url(cam.main_uri) or cam.main_uri
        lines.append(f"  - uri: {_yaml_quote(uri)}")
        lines.append(f"    sensor-id: {_yaml_quote(cam.camera_id)}")
        lines.append(f"    sensor-name: {_yaml_quote(cam.camera_id)}")
    has_rtsp = any((c.main_uri or "").lower().startswith("rtsp://") for c in cameras)
    # Live RTSP: keep pipeline up after a source EOS. File/inbox: propagate EOS and exit.
    drop_eos = (
        int(bool(drop_pipeline_eos))
        if drop_pipeline_eos is not None
        else (1 if live_source else 0)
    )
    mux_batch = max(1, len(cameras), int(max_batch_size or 0))
    reconnect = max(5, int(reconnect_s or 10))
    lines.extend(
        [
            "source-config:",
            "  source-bin: nvmultiurisrcbin",
            "  properties:",
            f"    max-batch-size: {mux_batch}",
            f"    live-source: {1 if live_source else 0}",
            f"    width: {width}",
            f"    height: {height}",
            "    batched-push-timeout: 40000",
            f"    drop-pipeline-eos: {drop_eos}",
            "    disable-audio: true",
        ]
    )
    if has_rtsp:
        lines.extend(
            [
                # GST_RTSP_LOWER_TRANS_TCP = 0x04
                "    select-rtp-protocol: 4",
                f"    rtsp-reconnect-interval: {reconnect}",
                "    rtsp-reconnect-attempts: -1",
                "    init-rtsp-reconnect-interval: 5",
                "    latency: 200",
            ]
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest
