"""Cut an incident clip from the ring-buffer (Campus incident_clip)."""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.ds.config import CameraConfig
from app.ds.ring_buffer import (
    camera_segment_dir,
    clips_root,
    edge_margin_s,
    safe_camera_dirname,
    segment_dur_sec,
    segment_root,
)

logger = logging.getLogger(__name__)

_LOCK_TTL_SEC = 60 * 30
_event_locks: dict[str, float] = {}
_event_locks_mu = threading.Lock()


def _ffmpeg_bin() -> str:
    for candidate in ("/usr/local/bin/ffmpeg", shutil.which("ffmpeg") or ""):
        if candidate and Path(candidate).is_file():
            return candidate
    return "ffmpeg"


def _acquire_event_lock(event_id: str) -> bool:
    now = time.monotonic()
    with _event_locks_mu:
        expired = [k for k, until in _event_locks.items() if until <= now]
        for k in expired:
            _event_locks.pop(k, None)
        if event_id in _event_locks:
            return False
        _event_locks[event_id] = now + _LOCK_TTL_SEC
        return True


def _release_event_lock(event_id: str) -> None:
    with _event_locks_mu:
        _event_locks.pop(event_id, None)


def segments_in_window(
    out_dir: Path,
    *,
    camera_prefix: str,
    start_ts: float,
    end_ts: float,
    margin: float,
) -> list[tuple[Path, float]]:
    try:
        files = [
            p
            for p in out_dir.iterdir()
            if p.is_file()
            and p.suffix.lower() == ".mp4"
            and p.name.startswith(camera_prefix)
        ]
    except FileNotFoundError:
        return []

    lo, hi = start_ts - margin, end_ts + margin
    candidates: list[tuple[Path, float]] = []
    for path in files:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if lo <= mtime <= hi:
            candidates.append((path, mtime))

    by_mtime: dict[float, Path] = {}
    for path, mtime in candidates:
        if mtime not in by_mtime:
            by_mtime[mtime] = path
            continue
        old = by_mtime[mtime]
        try:
            old_num = int(old.stem.rsplit("_", 1)[-1])
            new_num = int(path.stem.rsplit("_", 1)[-1])
            if new_num > old_num:
                by_mtime[mtime] = path
        except (ValueError, IndexError):
            pass

    return [
        (path, mtime) for mtime, path in sorted(by_mtime.items(), key=lambda x: x[0])
    ]


def concat_segments(segs: list[tuple[Path, float]], out_path: Path) -> bool:
    list_path = Path(str(out_path) + ".concat_list.txt")
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(list_path, "w", encoding="utf-8") as f:
            for seg_path, _mtime in segs:
                f.write(f"file '{seg_path.resolve().as_posix()}'\n")
        cmd = [
            _ffmpeg_bin(),
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_path),
            "-c",
            "copy",
            str(out_path),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if res.returncode != 0:
            logger.error("incident clip ffmpeg failed: %s", (res.stderr or "")[:500])
            return False
        return out_path.is_file() and out_path.stat().st_size > 0
    except Exception:
        logger.exception("incident clip concat exception")
        return False
    finally:
        try:
            list_path.unlink(missing_ok=True)
        except OSError:
            pass


def cut_clip_from_source_video(
    *,
    source_video: Path,
    out_path: Path,
    offset_s: float,
    pre_s: float,
    post_s: float,
) -> bool:
    if not source_video.is_file():
        logger.error("source video missing: %s", source_video)
        return False
    start = max(0.0, float(offset_s) - float(pre_s))
    duration = max(0.1, float(pre_s) + float(post_s))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _ffmpeg_bin(),
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(source_video),
        "-t",
        f"{duration:.3f}",
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        str(out_path),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if res.returncode != 0:
            logger.error("source-video ffmpeg failed: %s", (res.stderr or "")[:500])
            return False
        return out_path.is_file() and out_path.stat().st_size > 0
    except Exception:
        logger.exception("source-video ffmpeg exception")
        return False


def _parse_trigger_time(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        trigger_time = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if trigger_time.tzinfo is None:
        trigger_time = trigger_time.replace(tzinfo=timezone.utc)
    return trigger_time


def build_clip_from_payload(
    payload: dict[str, Any],
    cameras: dict[str, CameraConfig],
) -> dict[str, Any]:
    event_id = str(payload.get("event_id") or "unknown")
    camera_id = str(payload.get("camera_id") or "").strip()
    result: dict[str, Any] = {
        "event_id": event_id,
        "camera_id": camera_id,
        "status": "error",
        "clip_path": None,
        "segments": 0,
        "error": None,
    }

    if str(payload.get("category") or "") == "error":
        result["status"] = "skipped"
        result["error"] = "category=error"
        return result

    if not _acquire_event_lock(event_id):
        result["status"] = "duplicate"
        result["error"] = "event_id already processing or done"
        logger.info("incident clip duplicate event_id=%s", event_id)
        return result

    try:
        return _build_clip_locked(payload, cameras, result)
    except Exception:
        _release_event_lock(event_id)
        raise


def _build_clip_locked(
    payload: dict[str, Any],
    cameras: dict[str, CameraConfig],
    result: dict[str, Any],
) -> dict[str, Any]:
    event_id = result["event_id"]
    camera_id = result["camera_id"]
    cam = cameras.get(camera_id)
    if cam is None:
        result["error"] = f"camera not found: {camera_id}"
        logger.warning("incident clip: %s", result["error"])
        _release_event_lock(event_id)
        return result

    prefix = safe_camera_dirname(cam.name or camera_id)
    safe_event = "".join(c if c.isalnum() or c in "-_" else "_" for c in event_id)[:120]
    out_path = clips_root() / f"{prefix}__{safe_event}.mp4"
    pre_s = _as_float(payload.get("pre_s"), 5.0)
    post_s = _as_float(payload.get("post_s"), 15.0)

    source_video = str(payload.get("source_video") or "").strip()
    if source_video and not source_video.lower().startswith("rtsp://"):
        src = Path(source_video)
        raw_off = payload.get("source_offset_s")
        try:
            offset = (
                float(raw_off)
                if raw_off is not None and str(raw_off).strip() != ""
                else pre_s
            )
        except (TypeError, ValueError):
            offset = pre_s
        if offset > 24 * 3600:
            logger.warning(
                "incident clip: source_offset_s=%.1f looks like wall-clock; "
                "falling back to pre_s=%.1f",
                offset,
                pre_s,
            )
            offset = pre_s
        ok = cut_clip_from_source_video(
            source_video=src,
            out_path=out_path,
            offset_s=offset,
            pre_s=pre_s,
            post_s=post_s,
        )
        if not ok:
            result["error"] = f"source-video cut failed: {src}"
            _release_event_lock(event_id)
            return result
        result["status"] = "ok"
        result["clip_path"] = str(out_path)
        result["segments"] = 1
        return result

    ring = _ring_for_camera(cam, cameras)
    if ring is None:
        result["error"] = (
            f"segment dir missing: {camera_segment_dir(cam.name or camera_id)} "
            "(is incident ring-buffer running?)"
        )
        logger.warning("incident clip: %s", result["error"])
        _release_event_lock(event_id)
        return result
    out_dir, prefix = ring

    trigger_time = _parse_trigger_time(payload.get("trigger_time"))
    trigger_epoch = (
        trigger_time.timestamp() if trigger_time is not None else time.time()
    )
    start_ts = trigger_epoch - pre_s
    end_ts = trigger_epoch + post_s

    wait_until = end_ts + float(segment_dur_sec()) + 1.0
    now = time.time()
    if wait_until > now:
        wait_s = wait_until - now
        logger.info(
            "incident clip event=%s waiting %.1fs (pre=%.1f post=%.1f)",
            event_id,
            wait_s,
            pre_s,
            post_s,
        )
        time.sleep(wait_s)

    segs = segments_in_window(
        out_dir,
        camera_prefix=prefix,
        start_ts=start_ts,
        end_ts=end_ts,
        margin=edge_margin_s(),
    )
    result["segments"] = len(segs)
    if not segs:
        result["error"] = "no segments in window"
        logger.warning(
            "incident clip event=%s camera=%s no segments in [%.1f, %.1f] dir=%s "
            "(segment_root=%s)",
            event_id,
            cam.name or camera_id,
            start_ts,
            end_ts,
            out_dir,
            segment_root(),
        )
        _release_event_lock(event_id)
        return result

    ok = concat_segments(segs, out_path)
    if not ok:
        result["error"] = "ffmpeg concat failed"
        _release_event_lock(event_id)
        return result

    result["status"] = "ok"
    result["clip_path"] = str(out_path)
    logger.info(
        "incident clip ready event=%s path=%s segments=%s",
        event_id,
        out_path,
        len(segs),
    )
    return result


def _ring_for_camera(
    cam: CameraConfig,
    cameras: dict[str, CameraConfig],
) -> tuple[Path, str] | None:
    """Segment dir + filename prefix. Shared RTSP uses the camera that is actually recording."""
    own_prefix = safe_camera_dirname(cam.name or cam.camera_id)
    own_dir = camera_segment_dir(cam.name or cam.camera_id)
    if own_dir.is_dir():
        return own_dir, own_prefix

    uri = (cam.main_uri or "").strip().lower()
    if not uri:
        return None
    for other in cameras.values():
        if other.camera_id == cam.camera_id:
            continue
        if (other.main_uri or "").strip().lower() != uri:
            continue
        alt_prefix = safe_camera_dirname(other.name or other.camera_id)
        alt_dir = camera_segment_dir(other.name or other.camera_id)
        if alt_dir.is_dir():
            logger.info(
                "incident clip: camera=%s has no ring; using %s (same RTSP)",
                cam.camera_id,
                other.camera_id,
            )
            return alt_dir, alt_prefix
    return None


def _as_float(value: Any, default: float) -> float:
    try:
        if value is None or str(value).strip() == "":
            return default
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default
