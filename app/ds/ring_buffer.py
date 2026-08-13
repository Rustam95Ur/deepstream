"""
Incident ring-buffer: gst-launch + splitmuxsink, same as Campus ``rtsp_writer``.

Short local segments 24/7. Clips are cut later (wait pre/post → ffmpeg concat).
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.ds.rtsp import resolve_codec, sanitize_rtsp_url
from app.settings import _default_data_dir
from app.storage import get_store

logger = logging.getLogger(__name__)

GST_LAUNCH = "gst-launch-1.0"


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    return float(raw) if raw else default


def segment_dur_sec() -> int:
    return max(1, _env_int("NEXUS_DS_RING_SEGMENT_DUR_SEC", 3))


def keep_buffer_s() -> int:
    return max(30, _env_int("NEXUS_DS_RING_KEEP_S", 90))


def edge_margin_s() -> float:
    return max(0.0, _env_float("NEXUS_DS_RING_EDGE_MARGIN_S", 2.0))


def _latency_ms() -> int:
    return max(0, _env_int("NEXUS_DS_RING_LATENCY_MS", 200))


def _stagger_sec() -> float:
    return max(0.0, _env_float("NEXUS_DS_RING_STAGGER_SEC", 0.3))


def _health_interval_sec() -> int:
    return max(5, _env_int("NEXUS_DS_RING_HEALTH_CHECK_INTERVAL_SEC", 20))


def _stall_multiplier() -> float:
    return max(1.5, _env_float("NEXUS_DS_RING_STALL_MULTIPLIER", 3.0))


def _max_restart_backoff_sec() -> int:
    return max(1, _env_int("NEXUS_DS_RING_MAX_RESTART_BACKOFF_SEC", 60))


def _camera_refresh_sec() -> int:
    return max(15, _env_int("NEXUS_DS_RING_CAMERA_REFRESH_SEC", 60))


def _gc_interval_sec() -> int:
    return max(10, _env_int("NEXUS_DS_RING_GC_INTERVAL_SEC", 30))


def _muxer() -> str:
    raw = (_env("NEXUS_DS_RING_MUXER", "mp4mux") or "mp4mux").lower()
    return "qtmux" if raw == "qtmux" else "mp4mux"


def _default_codec() -> str:
    raw = (_env("NEXUS_DS_RING_DEFAULT_CODEC", "h265") or "h265").lower()
    return "h264" if raw == "h264" else "h265"


def safe_camera_dirname(name: str) -> str:
    return re.sub(r"[^\w.-]+", "_", name)[:64] or "camera"


def segment_root() -> Path:
    raw = _env("NEXUS_DS_RING_SEGMENT_DIR")
    if raw:
        root = Path(raw)
    else:
        root = _default_data_dir() / "incident_ring_buffer"
    root.mkdir(parents=True, exist_ok=True)
    return root


def clips_root() -> Path:
    raw = _env("NEXUS_DS_CLIPS_DIR")
    if raw:
        root = Path(raw)
    else:
        root = _default_data_dir() / "incident_clips"
    root.mkdir(parents=True, exist_ok=True)
    return root


def camera_segment_dir(camera_name: str, *, root: Path | None = None) -> Path:
    base = root if root is not None else segment_root()
    return base / safe_camera_dirname(camera_name)


def gst_launch_available() -> bool:
    return shutil.which(GST_LAUNCH) is not None


def _sigkill() -> int:
    return int(getattr(signal, "SIGKILL", signal.SIGTERM))


@dataclass(frozen=True, slots=True)
class CameraSpec:
    camera_id: str
    name: str
    rtsp_url: str


def load_rtsp_cameras() -> list[CameraSpec]:
    store = get_store()
    settings = store.get_settings()
    if not settings.enable_clip_record:
        return []
    specs: list[CameraSpec] = []
    for cam in store.list_cameras():
        if not cam.enabled:
            continue
        uri = (cam.main_uri or "").strip()
        if not uri.lower().startswith("rtsp://"):
            continue
        specs.append(
            CameraSpec(
                camera_id=cam.id,
                name=(cam.name or cam.id).strip() or cam.id,
                rtsp_url=uri,
            )
        )
    if len(specs) > settings.max_streams:
        specs = specs[: settings.max_streams]
    return specs


class IncidentRingBufferWorker:
    """gst-launch splitmuxsink → local segments (no upload)."""

    def __init__(self, spec: CameraSpec, *, segment_root_path: Path) -> None:
        self.spec = spec
        self.name = spec.name
        self.safe_name = safe_camera_dirname(spec.name)
        self.codec = resolve_codec(spec.rtsp_url, spec.name, default=_default_codec())
        self.out_dir = segment_root_path / self.safe_name
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.location_pattern = str(self.out_dir / f"{self.safe_name}_%05d.mp4")
        self.log_path = segment_root_path / "logs" / f"{self.safe_name}.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        self.process: subprocess.Popen | None = None
        self._log_fh = None
        self.started_at: float | None = None
        self.consecutive_restarts = 0
        self.total_restarts = 0

    def build_cmd(self) -> list[str]:
        url = sanitize_rtsp_url(self.spec.rtsp_url) or self.spec.rtsp_url
        depay = "rtph265depay" if self.codec == "h265" else "rtph264depay"
        parse = "h265parse" if self.codec == "h265" else "h264parse"
        max_size_ns = int(segment_dur_sec() * 1_000_000_000)
        return [
            GST_LAUNCH,
            "-e",
            "rtspsrc",
            f"location={url}",
            "protocols=tcp",
            f"latency={_latency_ms()}",
            "!",
            "application/x-rtp,media=video",
            "!",
            depay,
            "!",
            parse,
            "config-interval=1",
            "!",
            "splitmuxsink",
            f"location={self.location_pattern}",
            f"max-size-time={max_size_ns}",
            f"muxer-factory={_muxer()}",
            "send-keyframe-requests=true",
        ]

    def start(self) -> None:
        if shutil.which(GST_LAUNCH) is None:
            raise RuntimeError(f"{GST_LAUNCH} not found in PATH")
        self._close_log()
        cmd = self.build_cmd()
        log_f = open(self.log_path, "a", buffering=1, encoding="utf-8")
        log_f.write(
            f"\n=== RING START {datetime.now().isoformat()} codec={self.codec} ===\n"
        )
        log_f.write(" ".join(cmd) + "\n")
        self.process = subprocess.Popen(cmd, stdout=log_f, stderr=log_f)
        self.started_at = time.time()
        self._log_fh = log_f
        logger.info(
            "Incident ring-buffer [%s]: started pid=%s codec=%s segment=%ss -> %s",
            self.name,
            self.process.pid,
            self.codec,
            segment_dur_sec(),
            self.out_dir,
        )

    def is_alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def exit_code(self) -> int | None:
        return self.process.poll() if self.process else None

    def latest_segment_mtime(self) -> float | None:
        try:
            files = [
                p
                for p in self.out_dir.iterdir()
                if p.is_file() and p.suffix.lower() == ".mp4"
            ]
            if not files:
                return None
            return max(p.stat().st_mtime for p in files)
        except FileNotFoundError:
            return None

    def _close_log(self) -> None:
        if self._log_fh is None:
            return
        try:
            self._log_fh.close()
        except Exception:
            pass
        self._log_fh = None

    def kill(self, sig: int | None = None) -> None:
        sig = _sigkill() if sig is None else sig
        if self.process and self.process.poll() is None:
            try:
                self.process.send_signal(sig)
                self.process.wait(timeout=5)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
        self._close_log()

    def graceful_stop(self) -> None:
        if self.process and self.process.poll() is None:
            logger.info("Incident ring-buffer [%s]: stopping (SIGINT)", self.name)
            try:
                self.process.send_signal(signal.SIGINT)
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                logger.warning(
                    "Incident ring-buffer [%s]: SIGINT timeout, SIGKILL", self.name
                )
                self.process.kill()
                try:
                    self.process.wait(timeout=5)
                except Exception:
                    pass
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
        self._close_log()

    def restart_backoff_delay(self) -> float:
        return float(min(2**self.consecutive_restarts, _max_restart_backoff_sec()))


def gc_old_segments(
    workers: list[IncidentRingBufferWorker], keep_s: int
) -> None:
    cutoff = time.time() - keep_s
    for w in workers:
        try:
            for f in w.out_dir.iterdir():
                if not (f.is_file() and f.suffix.lower() == ".mp4"):
                    continue
                if not f.name.startswith(w.safe_name):
                    continue
                try:
                    if f.stat().st_mtime < cutoff:
                        f.unlink(missing_ok=True)
                except OSError:
                    pass
        except FileNotFoundError:
            pass
        except Exception:
            logger.exception("Incident ring-buffer GC error on %s", w.name)


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
                time.sleep(_stagger_sec())
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
                    time.sleep(_stagger_sec())
                except Exception:
                    logger.exception(
                        "Incident ring-buffer: failed to restart camera=%s", spec.name
                    )
                    self._workers.pop(cam_id, None)

        self._recording_active = bool(self._workers)

    def _health_tick(self) -> None:
        now = time.time()
        stall_after = segment_dur_sec() * _stall_multiplier()
        for w in list(self._workers.values()):
            if not w.is_alive():
                code = w.exit_code()
                delay = w.restart_backoff_delay()
                logger.warning(
                    "Incident ring-buffer [%s]: exited code=%s, restart in %.0fs",
                    w.name,
                    code,
                    delay,
                )
                time.sleep(delay)
                w.consecutive_restarts += 1
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
                try:
                    w.start()
                except Exception:
                    logger.exception(
                        "Incident ring-buffer [%s]: restart after stall failed",
                        w.name,
                    )
                continue

            w.consecutive_restarts = 0

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
        last_health = 0.0
        last_gc = 0.0

        while not self._shutdown.is_set():
            now = time.time()
            refresh_due = (
                now - last_refresh >= _camera_refresh_sec()
            ) or self._refresh_now.is_set()
            if refresh_due:
                self._refresh_now.clear()
                last_refresh = now
                specs = load_rtsp_cameras() if gst_launch_available() else []
                if gst_launch_available() and not specs:
                    logger.info("Incident ring-buffer: no enabled RTSP cameras")
                self._sync_workers(specs)

            if self._recording_active and now - last_health >= _health_interval_sec():
                last_health = now
                self._health_tick()

            if self._recording_active and now - last_gc >= _gc_interval_sec():
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


_manager: RingBufferManager | None = None


def get_ring_buffer() -> RingBufferManager:
    global _manager
    if _manager is None:
        _manager = RingBufferManager()
    return _manager
