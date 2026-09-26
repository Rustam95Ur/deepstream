"""Incident ring-buffer paths and camera specs (env via RuntimeEnv)."""

from __future__ import annotations

import logging
import re
import shutil
import signal
from dataclasses import dataclass
from pathlib import Path

from app.runtime_env import get_runtime_env
from app.storage import get_store

logger = logging.getLogger(__name__)

GST_LAUNCH = "gst-launch-1.0"

_ERR_MARKERS = (
    "ERROR",
    "Failed",
    "failed delayed",
    "Could not",
    "Internal Server",
    "Connection refused",
    "Not Found",
    "no element",
    "Received end-of-file",
)


def tail_log_error(path: Path) -> str:
    try:
        data = path.read_bytes()[-12_288:].decode("utf-8", errors="replace")
    except OSError:
        return ""
    for line in reversed(data.splitlines()):
        text = line.strip()
        if not text:
            continue
        if any(marker in text for marker in _ERR_MARKERS):
            return text[:400]
    return ""


def segment_dur_sec() -> int:
    return max(1, get_runtime_env().ring_segment_dur_sec)


def keep_buffer_s() -> int:
    return max(30, get_runtime_env().ring_keep_s)


def edge_margin_s() -> float:
    return max(0.0, get_runtime_env().ring_edge_margin_s)


def latency_ms() -> int:
    return max(0, get_runtime_env().ring_latency_ms)


def stagger_sec() -> float:
    return max(0.0, get_runtime_env().ring_stagger_sec)


def stall_multiplier() -> float:
    return max(1.5, get_runtime_env().ring_stall_multiplier)


def max_restart_backoff_sec() -> int:
    return max(1, get_runtime_env().ring_max_restart_backoff_sec)


def camera_refresh_sec() -> int:
    return max(15, get_runtime_env().ring_camera_refresh_sec)


def gc_interval_sec() -> int:
    return max(10, get_runtime_env().ring_gc_interval_sec)


def muxer() -> str:
    raw = get_runtime_env().ring_muxer
    return "qtmux" if raw == "qtmux" else "mp4mux"


def default_codec() -> str:
    raw = get_runtime_env().ring_default_codec
    return "h264" if raw == "h264" else "h265"


def safe_camera_dirname(name: str) -> str:
    return re.sub(r"[^\w.-]+", "_", name)[:64] or "camera"


def segment_root() -> Path:
    rt = get_runtime_env()
    raw = rt.ring_segment_dir
    if raw:
        root = Path(raw)
    else:
        root = rt.data_dir / "incident_ring_buffer"
    root.mkdir(parents=True, exist_ok=True)
    return root


def clips_root() -> Path:
    rt = get_runtime_env()
    raw = rt.clips_dir
    if raw:
        root = Path(raw)
    else:
        root = rt.data_dir / "incident_clips"
    root.mkdir(parents=True, exist_ok=True)
    return root


def camera_segment_dir(camera_name: str, *, root: Path | None = None) -> Path:
    base = root if root is not None else segment_root()
    return base / safe_camera_dirname(camera_name)


def gst_launch_available() -> bool:
    return shutil.which(GST_LAUNCH) is not None


def sigkill() -> int:
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
    seen_uri: set[str] = set()
    for cam in store.list_cameras():
        if not cam.enabled:
            continue
        uri = (cam.main_uri or "").strip()
        if not uri.lower().startswith("rtsp://"):
            continue
        key = uri.lower()
        if key in seen_uri:
            logger.warning(
                "Incident ring-buffer: skip duplicate RTSP camera=%s",
                cam.name or cam.id,
            )
            continue
        seen_uri.add(key)
        specs.append(
            CameraSpec(
                camera_id=cam.id,
                name=(cam.name or cam.id).strip() or cam.id,
                rtsp_url=uri,
            )
        )
    if len(specs) > settings.max_streams:
        dropped = specs[settings.max_streams :]
        specs = specs[: settings.max_streams]
        logger.warning(
            "Incident ring-buffer: truncated to max_streams=%s; skipped %s",
            settings.max_streams,
            ", ".join(s.camera_id for s in dropped),
        )
    return specs
