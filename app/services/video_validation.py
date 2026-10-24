"""Валидация видеозаписей: ffprobe-структура + детектор ghosting (I/P кадры)."""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.services.rtsp_probe import resolve_ffprobe_executable

logger = logging.getLogger(__name__)

# Минимальный средний размер P-кадра в байтах на мегапиксель.
# Битые файлы ~160 B/MP, чистые ~8000 B/MP.
MIN_P_FRAME_BYTES_PER_MEGAPIXEL = 800

# Минимальное отношение среднего размера P-кадра к среднему размеру I-кадра.
# Битые ~0.001, чистые ~0.045. Порог: 1%.
MIN_P_TO_I_RATIO = 0.01


@dataclass(frozen=True)
class VideoValidationResult:
    ok: bool
    reason: str
    duration_sec: float | None = None
    width: int | None = None
    height: int | None = None
    ffprobe_ok: bool | None = None
    ghosting_ok: bool | None = None
    details: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ffprobe_bin() -> str | None:
    return resolve_ffprobe_executable()


def ffprobe_check(
    video_path: str | Path,
) -> tuple[bool, str, float | None, int | None, int | None]:
    """Layer 1: structural ffprobe check."""
    path = str(video_path)
    ffprobe = _ffprobe_bin()
    if not ffprobe:
        return (
            False,
            "ffprobe не найден в системе (проверь установку ffmpeg)",
            None,
            None,
            None,
        )
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "format=duration:stream=codec_type,width,height",
        "-of",
        "json",
        path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        return False, "ffprobe timeout — файл, вероятно, поврежден", None, None, None
    except FileNotFoundError:
        return (
            False,
            "ffprobe не найден в системе (проверь установку ffmpeg)",
            None,
            None,
            None,
        )

    stderr = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return False, f"ffprobe вернул ошибку: {stderr[:200]}", None, None, None

    stderr_l = stderr.lower()
    if stderr and ("moov atom not found" in stderr_l or "invalid data" in stderr_l):
        return False, f"Поврежденный контейнер: {stderr[:200]}", None, None, None

    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return False, "Не удалось распарсить вывод ffprobe", None, None, None

    duration = data.get("format", {}).get("duration")
    if duration is None:
        return (
            False,
            "duration отсутствует в метаданных (файл, вероятно, оборван)",
            None,
            None,
            None,
        )

    try:
        duration_val = float(duration)
    except (TypeError, ValueError):
        return False, f"duration некорректен: {duration}", None, None, None

    if duration_val <= 0:
        return (
            False,
            f"duration = {duration_val} (нулевая длительность)",
            None,
            None,
            None,
        )

    streams = data.get("streams") or []
    if not streams:
        return False, "видеопоток не найден в файле", None, None, None

    width = streams[0].get("width")
    height = streams[0].get("height")
    return (
        True,
        f"структура OK, duration={duration_val:.2f}s",
        duration_val,
        width,
        height,
    )


def ghosting_check(
    video_path: str | Path,
    width: int | None,
    height: int | None,
    *,
    min_p_bytes_per_mp: float = MIN_P_FRAME_BYTES_PER_MEGAPIXEL,
    min_p_to_i_ratio: float = MIN_P_TO_I_RATIO,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Layer 2: детект ghosting по среднему размеру P-кадров.

    Слишком частые I-кадры + низкий битрейт => P-кадры почти без бит
    на движение => ghosting.
    """
    path = str(video_path)
    ffprobe = _ffprobe_bin()
    if not ffprobe:
        return False, "ffprobe не найден в системе", {}
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "frame=pict_type,pkt_size",
        "-of",
        "csv=p=0",
        path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return False, "ffprobe (анализ кадров) timeout", {}
    except FileNotFoundError:
        return False, "ffprobe не найден в системе", {}

    if proc.returncode != 0:
        return (
            False,
            f"ffprobe (анализ кадров) вернул ошибку: {(proc.stderr or '')[:200]}",
            {},
        )

    i_sizes: list[int] = []
    p_sizes: list[int] = []
    for line in (proc.stdout or "").splitlines():
        parts = line.strip().split(",")
        if len(parts) < 2:
            continue
        try:
            size = int(parts[0])
            pict_type = parts[1].strip()
        except (ValueError, IndexError):
            continue
        if pict_type == "I":
            i_sizes.append(size)
        elif pict_type == "P":
            p_sizes.append(size)

    if not p_sizes:
        return (
            True,
            "P-кадры отсутствуют, проверка ghosting неприменима",
            {
                "i_frames": len(i_sizes),
                "p_frames": 0,
            },
        )

    if not i_sizes:
        return (
            True,
            "I-кадры не найдены, проверка ghosting неприменима",
            {
                "i_frames": 0,
                "p_frames": len(p_sizes),
            },
        )

    avg_p = sum(p_sizes) / len(p_sizes)
    avg_i = sum(i_sizes) / len(i_sizes)
    ratio = avg_p / avg_i if avg_i else 0.0
    megapixels = (width * height / 1_000_000) if (width and height) else 2.07
    bytes_per_mp = avg_p / megapixels if megapixels else 0.0

    metrics = {
        "i_frames": len(i_sizes),
        "p_frames": len(p_sizes),
        "avg_i_bytes": round(avg_i, 1),
        "avg_p_bytes": round(avg_p, 1),
        "p_to_i_ratio": round(ratio, 6),
        "p_bytes_per_mp": round(bytes_per_mp, 1),
        "min_p_bytes_per_mp": min_p_bytes_per_mp,
        "min_p_to_i_ratio": min_p_to_i_ratio,
    }
    details = (
        f"I={len(i_sizes)} (avg={avg_i:.0f}B), P={len(p_sizes)} (avg={avg_p:.0f}B), "
        f"P/I ratio={ratio:.4f}, P bytes/MP={bytes_per_mp:.0f}"
    )

    if bytes_per_mp < min_p_bytes_per_mp or ratio < min_p_to_i_ratio:
        return (
            False,
            f"P-кадры недокодированы (вероятен ghosting на движении): {details}",
            metrics,
        )
    return True, f"кодирование движения в норме: {details}", metrics


def validate_video(video_path: str | Path) -> VideoValidationResult:
    """Полная проверка записи: структура + ghosting."""
    path = Path(video_path)
    if not path.is_file():
        return VideoValidationResult(ok=False, reason=f"файл не найден: {path}")

    ok, reason, duration, width, height = ffprobe_check(path)
    if not ok:
        return VideoValidationResult(
            ok=False,
            reason=f"[ffprobe] {reason}",
            ffprobe_ok=False,
            ghosting_ok=None,
        )

    ghost_ok, ghost_reason, metrics = ghosting_check(path, width, height)
    if not ghost_ok:
        return VideoValidationResult(
            ok=False,
            reason=f"[ghosting] {ghost_reason}",
            duration_sec=duration,
            width=width,
            height=height,
            ffprobe_ok=True,
            ghosting_ok=False,
            details=metrics,
        )

    return VideoValidationResult(
        ok=True,
        reason=f"[ffprobe] {reason}; [ghosting] {ghost_reason}",
        duration_sec=duration,
        width=width,
        height=height,
        ffprobe_ok=True,
        ghosting_ok=True,
        details=metrics,
    )
