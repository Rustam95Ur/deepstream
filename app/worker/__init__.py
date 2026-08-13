"""Background DeepStream pipeline manager."""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

from app.ds.config import app_config_from_settings
from app.ds.sink_factory import build_sink
from app.schemas import WorkerStatusOut
from app.storage import Store, get_bootstrap, get_store

logger = logging.getLogger(__name__)


def pipeline_available() -> tuple[bool, str]:
    try:
        import pyservicemaker  # noqa: F401

        return True, "pyservicemaker ok"
    except Exception as exc:
        return False, f"pyservicemaker unavailable: {exc}"


class PipelineManager:
    def __init__(self, store: Store | None = None) -> None:
        self.store = store or get_store()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._running = False
        self._active = False
        self._last_started_at: datetime | None = None
        self._last_error = ""
        self._camera_ids: list[str] = []
        self._reload_requested = threading.Event()

    def status(self) -> WorkerStatusOut:
        ok, avail_detail = pipeline_available()
        alive = bool(self._thread and self._thread.is_alive())
        running = self._active and alive
        return WorkerStatusOut(
            running=running,
            available=ok,
            detail=self._status_detail(ok, avail_detail, running),
            last_started_at=self._last_started_at,
            last_error=self._last_error,
            camera_ids=list(self._camera_ids),
        )

    def _status_detail(self, ok: bool, avail_detail: str, running: bool) -> str:
        if not running:
            return "остановлен" if ok else avail_detail
        if not ok:
            return avail_detail
        if self._running:
            n = len(self._camera_ids)
            return f"активен · {n} кам." if n else "активен"
        if self._last_error:
            return self._last_error
        return "запускается…"

    def request_reload(self) -> None:
        self._reload_requested.set()

    def start(self) -> WorkerStatusOut:
        with self._lock:
            self._active = True
            if self._thread and self._thread.is_alive():
                return self.status()
            self._stop.clear()
            self._last_error = ""
            self._thread = threading.Thread(
                target=self._loop, name="ds-pipeline", daemon=True
            )
            self._thread.start()
        return self.status()

    def stop(self) -> WorkerStatusOut:
        self._active = False
        self._stop.set()
        self._reload_requested.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=5.0)
        self._running = False
        return self.status()

    def _loop(self) -> None:
        boot = get_bootstrap()
        os.environ.setdefault("DEEPSTREAM_WORK_DIR", str(boot.work_dir))
        os.environ.setdefault("DEEPSTREAM_YOLO_DIR", str(boot.yolo_dir))
        os.environ.setdefault("DEEPSTREAM_DEBUG_DIR", str(boot.debug_dir))

        while not self._stop.is_set():
            settings = self.store.get_settings()
            cameras = [c for c in self.store.list_cameras() if c.enabled]
            self._camera_ids = [c.id for c in cameras]

            ok, detail = pipeline_available()
            if not ok:
                self._running = False
                self._last_error = detail
                logger.warning("Pipeline idle: %s", detail)
                self._wait_or_reload(15.0)
                continue

            if not cameras:
                self._running = False
                self._last_error = "нет включённых камер"
                logger.info("Pipeline idle: нет включённых камер")
                self._wait_or_reload(10.0)
                continue

            if len(cameras) > settings.max_streams:
                cameras = cameras[: settings.max_streams]
                logger.warning(
                    "Truncated cameras to max_streams=%s", settings.max_streams
                )

            cfg = app_config_from_settings(settings, cameras)
            sink = build_sink(settings, cameras=cfg.enabled_cameras)
            self._running = True
            self._last_started_at = datetime.now(timezone.utc)
            self._last_error = ""
            self._reload_requested.clear()

            try:
                from app.ds.pipeline import run_pipeline

                logger.info(
                    "Starting pipeline node=%s cameras=%s",
                    settings.node_id,
                    len(cameras),
                )
                # run_pipeline blocks until crash/EOS; we interrupt via process restart
                # on reload by checking flag between reconnects.
                while not self._stop.is_set() and not self._reload_requested.is_set():
                    run_pipeline(cfg, cfg.enabled_cameras, sink)
                    if self._stop.is_set() or self._reload_requested.is_set():
                        break
                    logger.warning(
                        "Pipeline returned; reconnect in %.0fs",
                        cfg.pipeline.reconnect_s,
                    )
                    self._wait_or_reload(max(1.0, cfg.pipeline.reconnect_s))
            except Exception as exc:
                self._last_error = str(exc)
                logger.exception("Pipeline crashed")
                self._wait_or_reload(max(1.0, settings.reconnect_s))
            finally:
                closer = getattr(sink, "close", None)
                if callable(closer):
                    closer()
                self._running = False

    def _wait_or_reload(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if self._stop.is_set() or self._reload_requested.is_set():
                return
            time.sleep(0.5)


_manager: PipelineManager | None = None


def get_manager() -> PipelineManager:
    global _manager
    if _manager is None:
        _manager = PipelineManager()
    return _manager
