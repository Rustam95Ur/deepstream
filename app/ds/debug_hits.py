"""Save trigger hits to a shared debug folder (JSON + optional source video)."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def debug_root() -> Path:
    raw = (os.environ.get("DEEPSTREAM_DEBUG_DIR") or "").strip()
    if not raw:
        data = (os.environ.get("NEXUS_DS_DATA_DIR") or "").strip()
        if data:
            raw = str(Path(data) / "debug")
        else:
            raw = str(Path(__file__).resolve().parents[2] / "data" / "debug")
    path = Path(raw)
    path.mkdir(parents=True, exist_ok=True)
    return path


def debug_inbox_dir() -> Path:
    path = debug_root() / "inbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def debug_hits_dir() -> Path:
    path = debug_root() / "hits"
    path.mkdir(parents=True, exist_ok=True)
    return path


def debug_processed_dir() -> Path:
    path = debug_root() / "processed"
    path.mkdir(parents=True, exist_ok=True)
    return path


def debug_save_enabled() -> bool:
    raw = (os.environ.get("DEEPSTREAM_DEBUG_SAVE_HITS") or "false").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _safe(value: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", value).strip("_")[:80] or "event"


def save_hit(
    payload: dict[str, Any],
    *,
    source_video: str | Path | None = None,
    force: bool = False,
) -> Path | None:
    if not force and not debug_save_enabled():
        return None
    try:
        hits = debug_hits_dir()
        event_id = _safe(str(payload.get("event_id") or "unknown"))
        trigger_type = _safe(str(payload.get("trigger_type") or "trigger"))
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base = f"{ts}_{event_id}_{trigger_type}"
        json_path = hits / f"{base}.json"
        body = dict(payload)
        body["debug_saved_at"] = datetime.now(timezone.utc).isoformat()
        if source_video:
            src = Path(source_video)
            if src.is_file():
                dest = hits / f"{base}{src.suffix.lower() or '.mp4'}"
                shutil.copy2(src, dest)
                body["debug_source_video"] = str(dest)
        json_path.write_text(
            json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("debug hit saved %s", json_path)
        return json_path
    except Exception:
        logger.exception("debug hit save failed")
        return None
