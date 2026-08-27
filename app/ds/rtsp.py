"""RTSP helpers for the incident ring-buffer (Campus rtsp_writer)."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote, unquote

logger = logging.getLogger(__name__)

CodecName = str  # "h264" | "h265"


def sanitize_rtsp_url(rtsp: str) -> str:
    """Percent-encode userinfo so ``#`` in a password does not become a fragment."""
    s = (rtsp or "").strip()
    if not s.lower().startswith("rtsp://"):
        return s
    rest = s[7:]
    slash = rest.find("/")
    if slash >= 0:
        netloc, path = rest[:slash], rest[slash:]
    else:
        netloc, path = rest, ""
    if "@" not in netloc:
        return s
    userinfo, hostport = netloc.rsplit("@", 1)
    colon = userinfo.find(":")
    if colon < 0:
        user_enc = quote(unquote(userinfo), safe="")
        return f"rtsp://{user_enc}@{hostport}{path}"
    user = quote(unquote(userinfo[:colon]), safe="")
    password = quote(unquote(userinfo[colon + 1 :]), safe="")
    return f"rtsp://{user}:{password}@{hostport}{path}"


def _ffprobe() -> str | None:
    for candidate in ("/usr/local/bin/ffprobe", shutil.which("ffprobe") or ""):
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def probe_codec(rtsp_url: str, *, timeout_sec: float = 6.0) -> CodecName | None:
    ffprobe = _ffprobe()
    if not ffprobe:
        return None
    safe_url = sanitize_rtsp_url(rtsp_url) or rtsp_url
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-rtsp_transport",
        "tcp",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=codec_name",
        "-of",
        "json",
        "-timeout",
        str(int(timeout_sec * 1_000_000)),
        "-i",
        safe_url,
    ]
    try:
        out = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout_sec + 3,
            text=True,
            check=False,
        )
        data = json.loads(out.stdout or "{}")
        codec_name = ((data.get("streams") or [{}])[0].get("codec_name") or "").lower()
        if "265" in codec_name or "hevc" in codec_name:
            return "h265"
        if "264" in codec_name or "avc" in codec_name:
            return "h264"
    except Exception:
        logger.debug("ffprobe codec probe failed url=%s", safe_url, exc_info=True)
    return None


def resolve_codec(
    rtsp_url: str, camera_name: str, default: CodecName = "h265"
) -> CodecName:
    probed = probe_codec(rtsp_url)
    if probed:
        logger.info("RTSP writer [%s]: codec from ffprobe=%s", camera_name, probed)
        return probed
    codec = "h264" if default == "h264" else "h265"
    logger.warning(
        "RTSP writer [%s]: codec probe failed, using default=%s",
        camera_name,
        codec,
    )
    return codec
