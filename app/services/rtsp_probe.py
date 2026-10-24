"""
Probe RTSP (and other ffmpeg-readable) URLs for video width, height, and FPS.
Uses ffprobe when available; falls back to parsing ffmpeg stderr.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.ds.rtsp import sanitize_rtsp_url

logger = logging.getLogger(__name__)

_STREAM_LINE_RE = re.compile(
    r"Video:[^\n]*?(\d+)x(\d+)",
    re.IGNORECASE,
)
_FPS_RE = re.compile(r"([\d.]+)\s*(?:fps|tbr)", re.IGNORECASE)


def _parse_fraction(s: str) -> float | None:
    if not s or s in ("0/0", "N/A"):
        return None
    if "/" in s:
        num, _, den = s.partition("/")
        try:
            d = float(den)
            if d == 0:
                return None
            return float(num) / d
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def _fps_from_ffprobe_stream(stream: dict[str, Any]) -> int | None:
    for key in ("r_frame_rate", "avg_frame_rate"):
        rate = _parse_fraction(str(stream.get(key) or ""))
        if rate and rate > 0:
            return max(1, round(rate))
    return None


def resolve_ffmpeg_executable() -> str | None:
    env_bin = (os.environ.get("FFMPEG_BINARY") or "").strip()
    if env_bin and Path(env_bin).is_file():
        return env_bin
    which = shutil.which("ffmpeg")
    if which:
        return which
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def resolve_ffprobe_executable() -> str | None:
    env_bin = (os.environ.get("FFPROBE_BINARY") or "").strip()
    if env_bin and Path(env_bin).is_file():
        return env_bin
    which = shutil.which("ffprobe")
    if which:
        return which
    ffmpeg = resolve_ffmpeg_executable()
    if not ffmpeg:
        return None
    p = Path(ffmpeg)
    name = p.name.lower()
    if name.endswith("ffmpeg.exe"):
        probe = p.with_name("ffprobe.exe")
    elif name == "ffmpeg":
        probe = p.with_name("ffprobe")
    else:
        probe = p.parent / "ffprobe"
    if probe.is_file():
        return str(probe)
    return None


def _probe_via_ffprobe(rtsp_url: str, *, timeout_sec: float) -> dict[str, Any]:
    ffprobe = resolve_ffprobe_executable()
    if not ffprobe:
        return {
            "ok": False,
            "error": "ffprobe not found (install ffmpeg or set FFPROBE_BINARY)",
        }

    cmd = [
        ffprobe,
        "-v",
        "error",
        "-rtsp_transport",
        "tcp",
        "-analyzeduration",
        "8000000",
        "-probesize",
        "8000000",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate,avg_frame_rate",
        "-of",
        "json",
        "-i",
        rtsp_url,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Probe timed out"}
    except OSError as exc:
        logger.exception("ffprobe failed to run")
        return {"ok": False, "error": str(exc)}

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        return {"ok": False, "error": err[:500]}

    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "error": "Invalid ffprobe output"}

    streams = data.get("streams") or []
    if not streams:
        return {"ok": False, "error": "No video stream found"}

    st = streams[0]
    w, h = st.get("width"), st.get("height")
    if not w or not h:
        return {"ok": False, "error": "Could not read resolution"}

    fps = _fps_from_ffprobe_stream(st)
    if fps is None:
        fps = 25

    return {
        "ok": True,
        "resolution_width": int(w),
        "resolution_height": int(h),
        "fps": int(fps),
    }


def _probe_via_ffmpeg_stderr(rtsp_url: str, *, timeout_sec: float) -> dict[str, Any]:
    ffmpeg = resolve_ffmpeg_executable()
    if not ffmpeg:
        return {"ok": False, "error": "ffmpeg not found"}

    cmd = [
        ffmpeg,
        "-hide_banner",
        "-rtsp_transport",
        "tcp",
        "-analyzeduration",
        "8000000",
        "-probesize",
        "8000000",
        "-i",
        rtsp_url,
        "-t",
        "0.5",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Probe timed out"}
    except OSError as exc:
        logger.exception("ffmpeg probe failed to run")
        return {"ok": False, "error": str(exc)}

    text = (proc.stderr or "") + "\n" + (proc.stdout or "")
    m = _STREAM_LINE_RE.search(text)
    if not m:
        err = text.strip()[-500:] if text.strip() else f"exit {proc.returncode}"
        return {"ok": False, "error": err}

    w, h = int(m.group(1)), int(m.group(2))
    fps_m = _FPS_RE.search(text[m.end() : m.end() + 120])
    if fps_m:
        fps = max(1, round(float(fps_m.group(1))))
    else:
        fps = 25

    return {
        "ok": True,
        "resolution_width": w,
        "resolution_height": h,
        "fps": fps,
    }


def probe_rtsp_url(rtsp_url: str, *, timeout_sec: float = 20.0) -> dict[str, Any]:
    """
    Return ``{ok, resolution_width, resolution_height, fps}`` or ``{ok: False, error}``.
    """
    url = sanitize_rtsp_url((rtsp_url or "").strip())
    if not url.lower().startswith("rtsp://"):
        return {"ok": False, "error": "URL must start with rtsp://"}

    result = _probe_via_ffprobe(url, timeout_sec=timeout_sec)
    if result.get("ok"):
        return result

    # Don't double the wait if ffprobe already hit the timeout.
    if result.get("error") == "Probe timed out":
        return result

    logger.info("ffprobe failed (%s), trying ffmpeg stderr parse", result.get("error"))
    fallback_timeout = min(timeout_sec, 12.0)
    return _probe_via_ffmpeg_stderr(url, timeout_sec=fallback_timeout)
