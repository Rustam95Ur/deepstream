"""
Тестовая запись камеры через gst-launch (TCP + H.264/H.265 → Matroska).

rtspsrc protocols=tcp → rtph*depay → *parse → matroskamux → filesink,
корректное завершение SIGINT.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from app.ds.rtsp import sanitize_rtsp_url
from app.services.video_validation import VideoValidationResult, validate_video

logger = logging.getLogger(__name__)

DEFAULT_TCP_MKV_DURATION_SEC = 12
MIN_TCP_MKV_DURATION_SEC = 5
MAX_TCP_MKV_DURATION_SEC = 60


@dataclass(frozen=True)
class TcpMkvRecordingResult:
    ok: bool
    output_path: str | None
    file_size_bytes: int
    duration_sec: int
    error: str | None = None
    stderr_tail: str | None = None
    validation: VideoValidationResult | None = None

    def as_dict(self) -> dict:
        data = asdict(self)
        if self.validation is not None:
            data["validation"] = self.validation.as_dict()
        return data


def _clamp_duration(duration_sec: int) -> int:
    return max(
        MIN_TCP_MKV_DURATION_SEC, min(int(duration_sec), MAX_TCP_MKV_DURATION_SEC)
    )


def build_tcp_mkv_gst_command(
    rtsp_url: str,
    output_path: Path,
    *,
    codec: str = "h265",
) -> list[str]:
    """Команда gst-launch для TCP H.264/H.265 → MKV (без перекодирования)."""
    codec_l = (codec or "h265").strip().lower()
    if codec_l in {"h264", "avc"}:
        depay, parse = "rtph264depay", "h264parse"
    else:
        depay, parse = "rtph265depay", "h265parse"
    return [
        "gst-launch-1.0",
        "-e",
        "rtspsrc",
        f"location={rtsp_url}",
        "protocols=tcp",
        "!",
        "application/x-rtp,media=video",
        "!",
        depay,
        "!",
        parse,
        "!",
        "matroskamux",
        "!",
        "filesink",
        f"location={output_path}",
    ]


def record_rtsp_tcp_mkv(
    rtsp_url: str,
    *,
    duration_sec: int = DEFAULT_TCP_MKV_DURATION_SEC,
    output_path: Path | None = None,
    validate: bool = True,
    codec: str = "h265",
) -> TcpMkvRecordingResult:
    """
    Короткая запись RTSP в MKV через gst-launch, затем опциональная валидация.
    """
    duration_sec = _clamp_duration(duration_sec)
    url = sanitize_rtsp_url((rtsp_url or "").strip())
    if not url:
        return TcpMkvRecordingResult(
            ok=False,
            output_path=None,
            file_size_bytes=0,
            duration_sec=duration_sec,
            error="RTSP URL is empty",
        )

    cleanup_output = False
    if output_path is None:
        fd, tmp_name = tempfile.mkstemp(suffix=".mkv", prefix="camera_tcp_mkv_")
        os.close(fd)
        output_path = Path(tmp_name)
        cleanup_output = True
    else:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists():
        try:
            output_path.unlink()
        except OSError:
            logger.warning("Cannot remove existing output %s", output_path)

    cmd = build_tcp_mkv_gst_command(url, output_path, codec=codec)
    logger.info(
        "TCP MKV recording start duration=%ss codec=%s out=%s",
        duration_sec,
        codec,
        output_path,
    )

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        if cleanup_output and output_path.exists():
            output_path.unlink(missing_ok=True)
        return TcpMkvRecordingResult(
            ok=False,
            output_path=None,
            file_size_bytes=0,
            duration_sec=duration_sec,
            error="gst-launch-1.0 не найден (нужен GStreamer на хосте)",
        )
    except Exception as exc:
        if cleanup_output and output_path.exists():
            output_path.unlink(missing_ok=True)
        return TcpMkvRecordingResult(
            ok=False,
            output_path=None,
            file_size_bytes=0,
            duration_sec=duration_sec,
            error=str(exc),
        )

    time.sleep(duration_sec)

    stderr_text = ""
    try:
        if hasattr(signal, "SIGINT"):
            process.send_signal(signal.SIGINT)
        else:
            process.terminate()
        _stdout, stderr = process.communicate(timeout=8)
        stderr_text = (stderr or b"").decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        process.kill()
        _stdout, stderr = process.communicate()
        stderr_text = (stderr or b"").decode("utf-8", errors="replace")
        logger.warning("TCP MKV recording: process killed after timeout")

    size = output_path.stat().st_size if output_path.is_file() else 0
    if size <= 0:
        if cleanup_output and output_path.exists():
            output_path.unlink(missing_ok=True)
        return TcpMkvRecordingResult(
            ok=False,
            output_path=None,
            file_size_bytes=0,
            duration_sec=duration_sec,
            error="Файл пустой или не создан",
            stderr_tail=stderr_text[-2000:] if stderr_text else None,
        )

    validation: VideoValidationResult | None = None
    if validate:
        validation = validate_video(output_path)
        if not validation.ok:
            return TcpMkvRecordingResult(
                ok=False,
                output_path=str(output_path),
                file_size_bytes=size,
                duration_sec=duration_sec,
                error=validation.reason,
                stderr_tail=stderr_text[-2000:] if stderr_text else None,
                validation=validation,
            )

    return TcpMkvRecordingResult(
        ok=True,
        output_path=str(output_path),
        file_size_bytes=size,
        duration_sec=duration_sec,
        validation=validation,
        stderr_tail=stderr_text[-2000:] if stderr_text else None,
    )


def record_camera_tcp_mkv_check(
    camera_id: str,
    rtsp_url: str,
    *,
    duration_sec: int = DEFAULT_TCP_MKV_DURATION_SEC,
    validate: bool = True,
    codec: str = "h265",
    output_dir: Path | None = None,
) -> TcpMkvRecordingResult:
    """Тестовая запись + проверка для камеры (id + RTSP URL)."""
    if output_dir is None:
        from app.runtime_env import get_runtime_env

        output_dir = get_runtime_env().data_dir / ".camera_recording_checks"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(camera_id))[
        :64
    ] or "camera"
    out = output_dir / f"camera_{safe_id}_{int(time.time())}.mkv"
    return record_rtsp_tcp_mkv(
        rtsp_url,
        duration_sec=duration_sec,
        output_path=out,
        validate=validate,
        codec=codec,
    )
