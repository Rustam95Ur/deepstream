"""Ring-buffer supervisor and process-wide manager facade."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from app.ds.ring_config import (
    GST_LAUNCH,
    CameraSpec,
    camera_refresh_sec,
    gc_interval_sec,
    gst_launch_available,
    keep_buffer_s,
    load_rtsp_cameras,
    segment_dur_sec,
    segment_root,
    stagger_sec,
    stall_multiplier,
    tail_log_error,
)
from app.ds.ring_worker import IncidentRingBufferWorker, gc_old_segments

logger = logging.getLogger(__name__)


class IncidentRingBufferSupervisor:
    def __init__(self) -> None:
        self._workers: dict[str, IncidentRingBufferWorker] = {}
        self._shutdown = threading.Event()
        self._refresh_now = threading.Event()
        self._segment_root = segment_root()
        self._recording_active = False

    def stop(self) -> None:
        self._shutdown.set()
        self._refresh_now.set()

    def request_refresh(self) -> None:
        self._refresh_now.set()

    def _stop_all_workers(self) -> None:
        threads: list[threading.Thread] = []
        for w in list(self._workers.values()):
            t = threading.Thread(target=w.graceful_stop, daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join(timeout=30)
        self._workers.clear()
        self._recording_active = False

    def _sync_workers(self, specs: list[CameraSpec]) -> None:
        wanted = {s.camera_id: s for s in specs}
        for cam_id in list(self._workers.keys()):
            if cam_id not in wanted:
                w = self._workers.pop(cam_id)
                w.graceful_stop()
                logger.info("Incident ring-buffer: removed camera id=%s", cam_id)

        for cam_id, spec in wanted.items():
            existing = self._workers.get(cam_id)
            if existing is None:
                worker = IncidentRingBufferWorker(
                    spec, segment_root_path=self._segment_root
                )
                try:
                    worker.start()
                except Exception:
                    logger.exception(
                        "Incident ring-buffer: failed to start camera=%s", spec.name
                    )
                    continue
                self._workers[cam_id] = worker
                time.sleep(stagger_sec())
                continue
            if (
                existing.spec.rtsp_url != spec.rtsp_url
                or existing.spec.name != spec.name
            ):
                logger.info(
                    "Incident ring-buffer: camera changed id=%s, restarting", cam_id
                )
                existing.graceful_stop()
                worker = IncidentRingBufferWorker(
                    spec, segment_root_path=self._segment_root
                )
                try:
                    worker.start()
                    self._workers[cam_id] = worker
                    time.sleep(stagger_sec())
                except Exception:
                    logger.exception(
                        "Incident ring-buffer: failed to restart camera=%s", spec.name
                    )
                    self._workers.pop(cam_id, None)

        self._recording_active = bool(self._workers)

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        stall_after = segment_dur_sec() * stall_multiplier()
        cameras: list[dict[str, Any]] = []
        for cam_id, w in list(self._workers.items()):
            mtime = w.latest_segment_mtime()
            age = (now - mtime) if mtime is not None else None
            stalled = bool(age is not None and age > stall_after)
            cameras.append(
                {
                    "camera_id": cam_id,
                    "name": w.name,
                    "alive": w.is_alive(),
                    "stalled": stalled,
                    "last_segment_age_s": round(age, 1) if age is not None else None,
                    "restarts": int(w.total_restarts),
                    "codec": w.codec,
                    "last_error": tail_log_error(w.log_path),
                }
            )
        return {
            "gst_available": gst_launch_available(),
            "ring_running": bool(self._recording_active),
            "cameras": cameras,
        }

    def _health_tick(self) -> None:
        now = time.time()
        stall_after = segment_dur_sec() * stall_multiplier()
        for w in list(self._workers.values()):
            if not w.is_alive():
                if w.next_restart_at <= 0:
                    w.schedule_restart(now)
                if now < w.next_restart_at:
                    continue
                w.next_restart_at = 0.0
                w.total_restarts += 1
                try:
                    w.start()
                except Exception:
                    logger.exception(
                        "Incident ring-buffer [%s]: restart failed", w.name
                    )
                continue

            mtime = w.latest_segment_mtime()
            if mtime is not None and w.started_at is not None:
                reference = max(mtime, w.started_at)
            elif mtime is not None:
                reference = mtime
            else:
                reference = w.started_at
            if reference is not None and (now - reference) > stall_after:
                logger.warning(
                    "Incident ring-buffer [%s]: stall %.0fs, hard restart",
                    w.name,
                    now - reference,
                )
                w.kill()
                w.consecutive_restarts += 1
                w.total_restarts += 1
                w._tried_codecs = {w.codec}
                try:
                    w.start()
                except Exception:
                    logger.exception(
                        "Incident ring-buffer [%s]: restart after stall failed",
                        w.name,
                    )
                continue

            w.consecutive_restarts = 0
            w.next_restart_at = 0.0
            w._tried_codecs = {w.codec}

    def run_forever(self) -> None:
        logger.info(
            "Incident ring-buffer starting segment_dir=%s segment_dur=%ss "
            "keep_buffer=%ss (24/7)",
            self._segment_root,
            segment_dur_sec(),
            keep_buffer_s(),
        )
        if not gst_launch_available():
            logger.error(
                "%s not found in PATH — incident ring-buffer cannot start",
                GST_LAUNCH,
            )

        last_refresh = 0.0
        last_gc = 0.0

        while not self._shutdown.is_set():
            now = time.time()
            refresh_due = (
                now - last_refresh >= camera_refresh_sec()
            ) or self._refresh_now.is_set()
            if refresh_due:
                self._refresh_now.clear()
                last_refresh = now
                specs = load_rtsp_cameras() if gst_launch_available() else []
                if gst_launch_available() and not specs:
                    logger.info("Incident ring-buffer: no enabled RTSP cameras")
                self._sync_workers(specs)

            if self._recording_active:
                self._health_tick()

            if self._recording_active and now - last_gc >= gc_interval_sec():
                last_gc = now
                gc_old_segments(list(self._workers.values()), keep_buffer_s())

            self._refresh_now.wait(1.0)

        self._stop_all_workers()
        logger.info("Incident ring-buffer stopped")


class RingBufferManager:
    def __init__(self) -> None:
        self._supervisor: IncidentRingBufferSupervisor | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._supervisor = IncidentRingBufferSupervisor()
            self._thread = threading.Thread(
                target=self._supervisor.run_forever,
                name="incident-ring-buffer",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        sup = self._supervisor
        if sup is not None:
            sup.stop()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=30.0)
        self._thread = None
        self._supervisor = None

    def request_refresh(self) -> None:
        if self._supervisor is not None:
            self._supervisor.request_refresh()

    def status(self) -> dict:
        sup = self._supervisor
        if sup is None:
            return {
                "gst_available": gst_launch_available(),
                "ring_running": False,
                "cameras": [],
            }
        return sup.snapshot()


_manager: RingBufferManager | None = None


def get_ring_buffer() -> RingBufferManager:
    global _manager
    if _manager is None:
        _manager = RingBufferManager()
    return _manager
