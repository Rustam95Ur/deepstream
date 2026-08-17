"""DeepStream Flow pipeline + metadata probe."""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from app.ds.config import AppConfig, CameraConfig
from app.ds.rtsp import sanitize_rtsp_url
from app.ds.triggers import Detection, TriggerEngine

logger = logging.getLogger(__name__)


def _obj_attr(obj: Any, *names: str, default=None):
    for name in names:
        if hasattr(obj, name):
            val = getattr(obj, name)
            if val is not None:
                return val
    return default


def _bbox_xywh(obj: Any) -> tuple[float, float, float, float] | None:
    rect = _obj_attr(obj, "rect_params", "rect", "bbox")
    if rect is not None:
        left = float(_obj_attr(rect, "left", "x", default=0) or 0)
        top = float(_obj_attr(rect, "top", "y", default=0) or 0)
        width = float(_obj_attr(rect, "width", "w", default=0) or 0)
        height = float(_obj_attr(rect, "height", "h", default=0) or 0)
        if width > 0 and height > 0:
            return left, top, width, height

    left = _obj_attr(obj, "left", "x")
    top = _obj_attr(obj, "top", "y")
    width = _obj_attr(obj, "width", "w")
    height = _obj_attr(obj, "height", "h")
    if None not in (left, top, width, height):
        w, h = float(width), float(height)
        if w > 0 and h > 0:
            return float(left), float(top), w, h
    return None


def _frame_video_seconds(frame_meta: Any) -> float | None:
    """Best-effort media time for file/inbox sources (PTS or frame_num)."""
    # Prefer buf_pts (media clock). Do NOT use ntp_timestamp — that is wall-clock.
    pts = _obj_attr(frame_meta, "buf_pts", "bufPts")
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
    frame_num = _obj_attr(frame_meta, "frame_num", "frameNum")
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
                    _obj_attr(frame_meta, "pad_index", "padIndex", default=0) or 0
                )
                video_s = _frame_video_seconds(frame_meta)
                if video_s is None:
                    fps = float(os.environ.get("DEEPSTREAM_INBOX_FPS", "25") or 25)
                    video_s = max(0.0, float(self._frames) / max(1.0, fps))
                engine.note_frame(pad_index, video_s=video_s)
                detections: list[Detection] = []
                for object_meta in frame_meta.object_items:
                    class_id = int(
                        _obj_attr(object_meta, "class_id", "classId", default=-1)
                    )
                    if class_id != person_class_id:
                        continue
                    conf = float(
                        _obj_attr(object_meta, "confidence", "conf", default=1.0) or 1.0
                    )
                    if conf < conf_threshold:
                        continue
                    box = _bbox_xywh(object_meta)
                    if not box:
                        continue
                    left, top, width, height = box
                    track_id = int(
                        _obj_attr(
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
    yolo_dir = Path(
        os.environ.get(
            "DEEPSTREAM_YOLO_DIR",
            "/opt/nexus_deepstream/models/yolo11n",
        )
    ).resolve()
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


def run_pipeline(
    app_cfg: AppConfig,
    cameras: list[CameraConfig],
    sink: Any,
    *,
    exit_on_eos: bool = False,
    interrupt: threading.Event | None = None,
    max_batch_size: int | None = None,
) -> None:
    from pyservicemaker import Flow, Pipeline, RenderMode

    engine = TriggerEngine(app_cfg, cameras, sink)

    stop = threading.Event()
    last_frame = {"t": 0.0, "n": 0}

    def _silent_watchdog():
        if exit_on_eos or not app_cfg.pipeline.live_source:
            return
        # Grace for TensorRT engine build + RTSP connect before stream_silent.
        grace = max(90.0, app_cfg.pipeline.stream_silent_s * 2)
        time.sleep(grace)
        while not stop.wait(5.0):
            try:
                engine.check_stream_silent()
            except Exception:
                logger.exception("stream_silent watchdog error")

    watchdog = threading.Thread(target=_silent_watchdog, name="silent-wd", daemon=True)
    watchdog.start()

    work_dir = Path(os.environ.get("DEEPSTREAM_WORK_DIR", "/tmp/nexus_deepstream"))
    yolo_dir = Path(
        os.environ.get(
            "DEEPSTREAM_YOLO_DIR",
            "/opt/nexus_deepstream/models/yolo11n",
        )
    )
    detector = (
        str(getattr(app_cfg.pipeline, "detector_model", "yolo11n") or "yolo11n")
        .strip()
        .lower()
    )
    if detector.startswith("yolo") and yolo_dir.is_dir():
        # DeepStream-Yolo custom engine I/O is CWD-relative (model_bN_gpu0_fp16.engine)
        os.chdir(yolo_dir)
        logger.info("CWD set to YOLO dir for engine cache: %s", yolo_dir)

    infer_batch = max(1, len(cameras))
    mux_batch = max(infer_batch, int(max_batch_size or 0))
    pgie = write_pgie_config(
        work_dir / "pgie.yml",
        batch_size=infer_batch,
        infer_interval=app_cfg.pipeline.infer_interval,
        conf_threshold=app_cfg.pipeline.conf_threshold,
        detector_model=detector,
    )
    sources = write_source_config(
        work_dir / "sources.yml",
        cameras,
        live_source=app_cfg.pipeline.live_source,
        width=app_cfg.pipeline.mux_width,
        height=app_cfg.pipeline.mux_height,
        drop_pipeline_eos=False if exit_on_eos else None,
        max_batch_size=mux_batch,
        reconnect_s=app_cfg.pipeline.reconnect_s,
    )

    def _note_frame(_n: int) -> None:
        last_frame["t"] = time.monotonic()
        last_frame["n"] += 1

    probe = build_probe(
        engine,
        person_class_id=app_cfg.pipeline.person_class_id,
        conf_threshold=app_cfg.pipeline.conf_threshold,
        on_frame=_note_frame if exit_on_eos else None,
    )

    logger.info(
        "Starting DeepStream pipeline cameras=%s mux_batch=%s live=%s exit_on_eos=%s pgie=%s sources=%s",
        len(cameras),
        mux_batch,
        app_cfg.pipeline.live_source,
        exit_on_eos,
        pgie,
        sources,
    )
    for i, cam in enumerate(cameras):
        logger.info("  pad=%s camera_id=%s uri=%s", i, cam.camera_id, cam.main_uri)

    pipeline = Pipeline("nexus-deepstream-incidents")
    flow = (
        Flow(pipeline)
        .batch_capture(str(sources))
        .infer(str(pgie))
        .attach(what=probe)
        .render(mode=RenderMode.DISCARD, enable_osd=False, sync=False)
    )

    def _stop_pipeline(reason: str) -> None:
        """Ask Flow/Pipeline to leave PLAYING. Safe to call repeatedly."""
        for obj in (pipeline, flow):
            for name in ("stop", "quit", "shutdown"):
                fn = getattr(obj, name, None)
                if not callable(fn):
                    continue
                try:
                    fn()
                except Exception:
                    logger.exception("%s.%s failed (%s)", type(obj).__name__, name, reason)
        native = None
        for attr in ("_pipeline", "pipeline", "gst_pipeline"):
            candidate = getattr(pipeline, attr, None)
            if candidate is not None and candidate is not pipeline:
                native = candidate
                break
        if native is None:
            return
        try:
            from gi.repository import Gst  # type: ignore

            send_event = getattr(native, "send_event", None)
            set_state = getattr(native, "set_state", None)
            if callable(send_event):
                send_event(Gst.Event.new_eos())
            if callable(set_state):
                set_state(Gst.State.NULL)
        except Exception:
            logger.exception("native Gst stop failed (%s)", reason)

    def _eos_idle_watchdog():
        """If drop-pipeline-eos still leaves Flow hung, stop after frames go idle."""
        idle_s = float(os.environ.get("DEEPSTREAM_INBOX_EOS_IDLE_S", "3") or 3)
        # Wait until first frame (engine build + decode can take minutes)
        while not stop.wait(0.5):
            if last_frame["n"] > 0:
                break
        while not stop.wait(0.5):
            if last_frame["n"] > 0 and (time.monotonic() - last_frame["t"]) >= idle_s:
                _stop_pipeline(f"inbox idle {idle_s:.1f}s after last frame")
                break

    eos_wd: threading.Thread | None = None
    if exit_on_eos:
        eos_wd = threading.Thread(
            target=_eos_idle_watchdog, name="eos-idle", daemon=True
        )
        eos_wd.start()

    def _interrupt_watch() -> None:
        if interrupt is None:
            return
        attempts = 0
        while not stop.wait(0.4):
            if not interrupt.is_set():
                continue
            attempts += 1
            if attempts == 1 or attempts % 15 == 0:
                logger.info("reload requested — stopping live pipeline (attempt %s)", attempts)
            _stop_pipeline("reload")

    if interrupt is not None:
        threading.Thread(
            target=_interrupt_watch, name="ds-interrupt", daemon=True
        ).start()

    try:
        flow()
    finally:
        stop.set()
        logger.info("DeepStream pipeline stopped")
