"""Per-camera gst-launch splitmuxsink worker."""

from __future__ import annotations

import logging
import shutil
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path

from app.ds.ring_config import (
    GST_LAUNCH,
    CameraSpec,
    default_codec,
    latency_ms,
    max_restart_backoff_sec,
    muxer,
    safe_camera_dirname,
    segment_dur_sec,
    sigkill,
)
from app.ds.rtsp import sanitize_rtsp_url

logger = logging.getLogger(__name__)


class IncidentRingBufferWorker:
    """gst-launch splitmuxsink → local segments (no upload)."""

    def __init__(self, spec: CameraSpec, *, segment_root_path: Path) -> None:
        self.spec = spec
        self.name = spec.name
        self.safe_name = safe_camera_dirname(spec.name)
        self.codec = default_codec()
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
        self._tried_codecs: set[str] = set()
        self.next_restart_at: float = 0.0

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
            f"latency={latency_ms()}",
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
            f"muxer-factory={muxer()}",
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
        self.next_restart_at = 0.0
        self._tried_codecs.add(self.codec)
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
        sig = sigkill() if sig is None else sig
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
        return float(min(2**self.consecutive_restarts, max_restart_backoff_sec()))

    def maybe_flip_codec_after_crash(self) -> bool:
        """Quick gst death is usually the wrong depay (H264 vs H265)."""
        started = self.started_at
        if started is None or (time.time() - started) > 8.0:
            self._tried_codecs = {self.codec}
            return False
        nxt = "h264" if self.codec == "h265" else "h265"
        if nxt in self._tried_codecs:
            return False
        logger.warning(
            "Incident ring-buffer [%s]: codec %s died in %.1fs, trying %s",
            self.name,
            self.codec,
            time.time() - started,
            nxt,
        )
        self.codec = nxt
        return True

    def schedule_restart(self, now: float) -> None:
        if self.next_restart_at > 0:
            return
        self._close_log()
        flipped = self.maybe_flip_codec_after_crash()
        if flipped:
            delay = 0.4
        else:
            self.consecutive_restarts += 1
            delay = self.restart_backoff_delay()
        self.next_restart_at = now + delay
        logger.warning(
            "Incident ring-buffer [%s]: exited code=%s codec=%s, restart in %.1fs",
            self.name,
            self.exit_code(),
            self.codec,
            delay,
        )


def gc_old_segments(workers: list[IncidentRingBufferWorker], keep_s: int) -> None:
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
