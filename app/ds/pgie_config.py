"""DeepStream PGIE (nvinfer) and nvmultiurisrcbin YAML writers."""

from __future__ import annotations

from pathlib import Path

from app.ds.config import CameraConfig
from app.ds.rtsp import sanitize_rtsp_url
from app.runtime_env import get_runtime_env


def write_pgie_config(
    dest: Path,
    *,
    batch_size: int,
    infer_interval: int,
    conf_threshold: float,
    detector_model: str = "yolo11n",
) -> Path:
    """Generate nvinfer INI for YOLO11n (DeepStream-Yolo custom parser)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    model = (detector_model or "yolo11n").strip().lower()
    if model and not model.startswith("yolo"):
        raise ValueError(f"Unsupported detector_model={model!r}; only yolo11n is wired")

    # nvinfer resolves relative paths against the config file dir (/tmp/...),
    # so use absolute paths. Still chdir to yolo_dir in run_pipeline because
    # NvDsInferYoloCudaEngineGet serializes engine as CWD/model_bN_gpu0_fp16.engine.
    yolo_dir = get_runtime_env().yolo_dir.resolve()
    onnx = yolo_dir / "yolo11n.onnx"
    labels = yolo_dir / "labels.txt"
    custom_lib = (
        yolo_dir / "nvdsinfer_custom_impl_Yolo" / "libnvdsinfer_custom_impl_Yolo.so"
    )
    engine = yolo_dir / f"model_b{batch_size}_gpu0_fp16.engine"

    if not onnx.is_file():
        raise FileNotFoundError(
            f"YOLO11n ONNX missing: {onnx}. Run models/yolo11n/prepare.sh"
        )
    if not custom_lib.is_file():
        raise FileNotFoundError(
            f"YOLO custom parser missing: {custom_lib}. Run models/yolo11n/prepare.sh"
        )

    # nvinfer `interval` = batches to SKIP (0 = every frame). Node setting is
    # "every Nth frame" (1 = every frame), so skip = N - 1.
    skip = max(0, int(infer_interval) - 1)
    text = f"""[property]
gpu-id=0
net-scale-factor=0.0039215697906911373
model-color-format=0
onnx-file={onnx.as_posix()}
model-engine-file={engine.as_posix()}
labelfile-path={labels.as_posix()}
batch-size={batch_size}
network-mode=2
num-detected-classes=80
interval={skip}
gie-unique-id=1
process-mode=1
network-type=0
cluster-mode=2
maintain-aspect-ratio=1
symmetric-padding=1
parse-bbox-func-name=NvDsInferParseYolo
custom-lib-path={custom_lib.as_posix()}
engine-create-func-name=NvDsInferYoloCudaEngineGet

[class-attrs-all]
nms-iou-threshold=0.45
pre-cluster-threshold={conf_threshold}
topk=300
"""
    if dest.suffix.lower() in (".yml", ".yaml"):
        dest = dest.with_suffix(".txt")
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
