"""DeepStream Flow runner (change-control: EOS / reload / chdir)."""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

from app.ds.config import AppConfig, CameraConfig
from app.ds.pgie_config import write_pgie_config, write_source_config
from app.ds.probe import build_probe
from app.ds.triggers import TriggerEngine
from app.runtime_env import get_runtime_env

logger = logging.getLogger(__name__)


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

    engine = TriggerEngine(app_cfg, cameras, sink, halt=interrupt)

    stop = threading.Event()
    last_frame = {"t": 0.0, "n": 0}

    def _silent_watchdog():
        if exit_on_eos or not app_cfg.pipeline.live_source:
            return
        # Grace for TensorRT engine build + RTSP connect before stream_silent.
        grace = max(90.0, app_cfg.pipeline.stream_silent_s * 2)
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            if stop.wait(0.5):
                return
            if interrupt is not None and interrupt.is_set():
                return
        while not stop.wait(5.0):
            if interrupt is not None and interrupt.is_set():
                return
            try:
                engine.check_stream_silent()
            except Exception:
                logger.exception("stream_silent watchdog error")

    watchdog = threading.Thread(target=_silent_watchdog, name="silent-wd", daemon=True)
    watchdog.start()

    rt = get_runtime_env()
    work_dir = rt.work_dir
    yolo_dir = rt.yolo_dir
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

    stop_lock = threading.Lock()
    stop_phase = {"n": 0}  # 0=idle, 1=soft, 2=hard

    def _unwrap_gst(obj: Any) -> Any | None:
        """Best-effort unwrap of service-maker Pipeline → Gst.Element."""
        if obj is None:
            return None
        try:
            from gi.repository import Gst  # type: ignore

            if isinstance(obj, Gst.Element):
                return obj
        except Exception:
            pass
        for name in (
            "_pipeline",
            "pipeline",
            "gst_pipeline",
            "_gst_pipeline",
            "native",
            "_native",
            "impl",
            "_impl",
        ):
            try:
                cand = getattr(obj, name, None)
            except Exception:
                continue
            if cand is None or cand is obj:
                continue
            found = _unwrap_gst(cand)
            if found is not None:
                return found
        try:
            raw = getattr(obj, "__dict__", None)
        except Exception:
            raw = None
        if isinstance(raw, dict):
            for cand in raw.values():
                if cand is None or cand is obj:
                    continue
                try:
                    from gi.repository import Gst  # type: ignore

                    if isinstance(cand, Gst.Element):
                        return cand
                except Exception:
                    continue
        return None

    def _iter_gst_elements(root: Any):
        from gi.repository import Gst  # type: ignore

        if root is None:
            return
        yield root
        iterate = getattr(root, "iterate_recurse", None)
        if not callable(iterate):
            return
        try:
            it = iterate()
        except Exception:
            return
        while True:
            try:
                result, value = it.next()
            except Exception:
                break
            if result == Gst.IteratorResult.OK:
                yield value
            elif result == Gst.IteratorResult.RESYNC:
                try:
                    it.resync()
                except Exception:
                    break
            else:
                break

    def _allow_eos_end(native: Any) -> int:
        """
        Live RTSP uses drop-pipeline-eos=1 so EOS from Pipeline.stop() is
        swallowed and Flow() never returns. Clear it before stop/EOS.
        """
        changed = 0
        for elem in _iter_gst_elements(native):
            try:
                if elem.find_property("drop-pipeline-eos") is None:
                    continue
                elem.set_property("drop-pipeline-eos", False)
                changed += 1
            except Exception:
                continue
            # Stop endless RTSP reconnect while we tear down.
            try:
                if elem.find_property("rtsp-reconnect-attempts") is not None:
                    elem.set_property("rtsp-reconnect-attempts", 0)
            except Exception:
                pass
        return changed

    def _set_null(native: Any) -> None:
        from gi.repository import Gst  # type: ignore

        try:
            native.set_state(Gst.State.NULL)
        except Exception:
            logger.exception("Gst set_state(NULL) failed")
        # Flush can unblock pads stuck in RTSP try_send.
        try:
            native.send_event(Gst.Event.new_flush_start())
            native.send_event(Gst.Event.new_flush_stop(True))
        except Exception:
            pass

    def _stop_pipeline(reason: str, *, hard: bool = False) -> None:
        """Leave PLAYING. Soft: allow EOS + Pipeline.stop. Hard: force NULL."""
        with stop_lock:
            native = _unwrap_gst(pipeline) or _unwrap_gst(flow)
            if native is not None:
                n = _allow_eos_end(native)
                if n:
                    logger.info(
                        "cleared drop-pipeline-eos on %s element(s) (%s)", n, reason
                    )
            # Service-maker stop posts EOS and quits the GLoop — only after
            # drop-pipeline-eos is cleared, otherwise EOS is discarded forever.
            for obj in (pipeline, flow):
                for name in ("stop", "quit", "shutdown"):
                    fn = getattr(obj, name, None)
                    if not callable(fn):
                        continue
                    try:
                        fn()
                    except Exception:
                        logger.exception(
                            "%s.%s failed (%s)", type(obj).__name__, name, reason
                        )
            if hard and native is not None:
                logger.warning("hard-stop pipeline (%s)", reason)
                _set_null(native)

    def _eos_idle_watchdog():
        """If drop-pipeline-eos still leaves Flow hung, stop after frames go idle."""
        idle_s = float(os.environ.get("DEEPSTREAM_INBOX_EOS_IDLE_S", "3") or 3)
        # Wait until first frame (engine build + decode can take minutes)
        while not stop.wait(0.5):
            if last_frame["n"] > 0:
                break
        while not stop.wait(0.5):
            if last_frame["n"] > 0 and (time.monotonic() - last_frame["t"]) >= idle_s:
                _stop_pipeline(f"inbox idle {idle_s:.1f}s after last frame", hard=True)
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
        # Wait until reload/stop is requested.
        while not stop.wait(0.4):
            if interrupt.is_set():
                break
        if stop.is_set() or interrupt is None or not interrupt.is_set():
            return
        logger.info("reload requested — stopping live pipeline")
        stop_phase["n"] = 1
        _stop_pipeline("reload", hard=False)
        # Soft stop often enough; escalate to NULL if Flow stays blocked.
        soft_deadline = time.monotonic() + 3.0
        hard_deadline = time.monotonic() + 12.0
        exit_after = float(os.environ.get("DEEPSTREAM_RELOAD_EXIT_S", "45") or 45)
        exit_deadline = time.monotonic() + max(20.0, exit_after)
        last_hard_log = 0.0
        while not stop.wait(1.0):
            if not interrupt.is_set():
                return
            now = time.monotonic()
            if now >= exit_deadline:
                logger.error(
                    "Flow hung after reload stop — exiting video process "
                    "(docker will restart with updated cameras)"
                )
                os._exit(75)
            if now >= hard_deadline:
                if stop_phase["n"] < 2:
                    stop_phase["n"] = 2
                    _stop_pipeline("reload-hard", hard=True)
                    last_hard_log = now
                elif now - last_hard_log >= 10.0:
                    last_hard_log = now
                    logger.error(
                        "pipeline still blocked after hard stop — "
                        "waiting for Flow() to return (exit in %.0fs)",
                        max(0.0, exit_deadline - now),
                    )
                continue
            if now >= soft_deadline:
                _stop_pipeline("reload-retry", hard=False)
                soft_deadline = now + 2.0

    if interrupt is not None:
        threading.Thread(
            target=_interrupt_watch, name="ds-interrupt", daemon=True
        ).start()

    try:
        flow()
    finally:
        stop.set()
        logger.info("DeepStream pipeline stopped")
