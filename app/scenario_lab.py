"""Replay incident clips already stored in history and MinIO.

The video process downloads each clip and plays it through the same detector
as a live camera. ``run.json`` keeps the last pass.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.db import db_enabled, session_scope
from app.ds.payload import clip_from_payload
from app.models import TriggerEventRow
from app.runtime_env import get_runtime_env
from app.trigger_types import TRIGGER_TYPES

MAX_BYTES = 800 * 1024 * 1024
REPLAY_LIMIT = 8
_SCAN_LIMIT = 60
NO_MODEL = frozenset({"fall", "smoke"})

SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "id": "presence",
        "label": "Присутствие",
        "ready": True,
        "hint": "Берутся последние ролики этого типа из истории. Файл читается из MinIO и снова смотрится как поток.",
    },
    {
        "id": "convergence",
        "label": "Сходка",
        "ready": True,
        "hint": "Двое сближаются. Пороги те же, что на ноде. На прогоне пауза между сходкой и дракой снята, чтобы были видны оба правила.",
    },
    {
        "id": "vif",
        "label": "Драка",
        "ready": True,
        "hint": "Боксы пересеклись и контакт держится. Пороги те же, что в разделе «Сценарии».",
    },
    {
        "id": "fall",
        "label": "Падение",
        "ready": False,
        "hint": "Веса ещё не подключены. Ролик всё равно прогоняется: падение само не отметится, остальные сценарии на нём будут видны.",
    },
    {
        "id": "smoke",
        "label": "Курение",
        "ready": False,
        "hint": "Веса ещё не подключены. Ролик всё равно прогоняется: курение само не отметится, остальные сценарии на нём будут видны.",
    },
    {
        "id": "stream_silent",
        "label": "Камера молчит",
        "ready": True,
        "hint": "Ролик для тишины потока обычно не сохраняется. Если файл в истории есть, прогон его посмотрит. Сама «тишина» на готовом ролике не подтверждается.",
    },
)

class LabError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def lab_root(root: Path | None = None) -> Path:
    if root is not None:
        return Path(root)
    return get_runtime_env().data_dir / "scenario_lab"


def scenario_ids() -> tuple[str, ...]:
    return tuple(str(item["id"]) for item in SCENARIOS)


def scenario_meta(scenario: str) -> dict[str, Any]:
    key = (scenario or "").strip().lower()
    for item in SCENARIOS:
        if item["id"] == key:
            return item
    raise LabError(400, f"неизвестный сценарий «{scenario}»")


def ensure_dirs(root: Path | None = None) -> Path:
    base = lab_root(root)
    base.mkdir(parents=True, exist_ok=True)
    return base


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty_run() -> dict[str, Any]:
    return {
        "status": "idle",
        "scenario": "",
        "started_at": "",
        "finished_at": "",
        "paused_live": False,
        "current_scenario": "",
        "current_event": "",
        "current_file": "",
        "error": "",
        "results": [],
    }


def run_path(root: Path | None = None) -> Path:
    return ensure_dirs(root) / "run.json"


def read_run(root: Path | None = None) -> dict[str, Any]:
    path = lab_root(root) / "run.json"
    if not path.is_file():
        return empty_run()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_run()
    if not isinstance(raw, dict):
        return empty_run()
    run = empty_run()
    run.update({k: raw.get(k, run[k]) for k in run})
    results = raw.get("results")
    run["results"] = results if isinstance(results, list) else []
    return run


def write_run(run: dict[str, Any], root: Path | None = None) -> None:
    path = run_path(root)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def mark_stale_run(root: Path | None = None) -> None:
    """A restarted video process cannot still be inside a lab pipeline."""
    run = read_run(root)
    if run.get("status") != "running":
        return
    run["status"] = "error"
    run["error"] = "видео-сервис перезапустился во время прогона"
    run["finished_at"] = utc_now()
    run["current_file"] = ""
    run["current_event"] = ""
    run["current_scenario"] = ""
    write_run(run, root)


def clip_ready(payload: dict[str, Any]) -> bool:
    """True when history kept a MinIO key or a local file for this event."""
    clip = clip_from_payload(payload)
    if (clip.get("key") or "").strip():
        return True
    path = (clip.get("path") or "").strip()
    return bool(path and Path(path).is_file())


def _clip_size(clip: dict[str, str]) -> int:
    raw = (clip.get("size") or "").strip()
    if not raw:
        return 0
    try:
        number = int(raw)
    except ValueError:
        return 0
    return number if number > 0 else 0


def replay_clips(scenario: str, *, limit: int = REPLAY_LIMIT) -> list[dict[str, Any]]:
    """Newest history rows of this type that still have a clip."""
    meta = scenario_meta(scenario)
    if not db_enabled():
        return []
    stmt = (
        select(TriggerEventRow)
        .where(TriggerEventRow.trigger_type == str(meta["id"]))
        .order_by(TriggerEventRow.created_at.desc(), TriggerEventRow.id.desc())
        .limit(_SCAN_LIMIT)
    )
    with session_scope(write=False) as session:
        rows = list(session.scalars(stmt).all())
    out: list[dict[str, Any]] = []
    for row in rows:
        payload = dict(row.payload or {})
        if not clip_ready(payload):
            continue
        clip = clip_from_payload(payload)
        created = row.created_at
        out.append(
            {
                "scenario": str(meta["id"]),
                "event_id": row.event_id,
                "camera_id": row.camera_id or "",
                "camera_name": str(payload.get("camera_name") or row.camera_id or ""),
                "created_at": created.isoformat() if created is not None else "",
                "size": _clip_size(clip),
                "key": (clip.get("key") or "").strip(),
                "bucket": (clip.get("bucket") or "").strip(),
                "path": (clip.get("path") or "").strip(),
            }
        )
        if len(out) >= limit:
            break
    return out


def clips_for_run(scenario: str) -> list[dict[str, Any]]:
    chosen = (scenario or "").strip().lower()
    ids = scenario_ids() if not chosen else (scenario_meta(chosen)["id"],)
    rows: list[dict[str, Any]] = []
    for scenario_id in ids:
        rows.extend(replay_clips(scenario_id))
    return rows


def materialize_clip(item: dict[str, Any], dest_dir: Path) -> tuple[Path, bool]:
    """Return a local mp4. The bool is true when the caller should delete it."""
    path = Path(str(item.get("path") or ""))
    if str(item.get("path") or "") and path.is_file():
        return path, False
    key = str(item.get("key") or "").strip()
    if not key:
        raise LabError(404, "у события нет ролика в MinIO")
    from app.minio_store import get_minio_store

    streamed = get_minio_store().iter_object(key)
    if streamed is None:
        raise LabError(404, "ролик не найден в MinIO")
    chunks, length = streamed
    if length and length > MAX_BYTES:
        for _ in chunks:
            pass
        raise LabError(413, "ролик больше 800 МБ")
    dest_dir.mkdir(parents=True, exist_ok=True)
    event_id = str(item.get("event_id") or "clip")
    dest = dest_dir / f"{event_id}.mp4"
    tmp = dest.with_suffix(".part")
    total = 0
    try:
        with tmp.open("wb") as out:
            for chunk in chunks:
                total += len(chunk)
                if total > MAX_BYTES:
                    raise LabError(413, "ролик больше 800 МБ")
                out.write(chunk)
        if total <= 0:
            raise LabError(404, "пустой ролик в MinIO")
        tmp.replace(dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return dest, True


def judge(expected: str, detected: list[str]) -> str:
    kinds = []
    seen: set[str] = set()
    known = set(TRIGGER_TYPES)
    for item in detected:
        name = str(item or "").strip().lower()
        if name in known and name not in seen:
            seen.add(name)
            kinds.append(name)
    if expected == "stream_silent":
        return "file_skip"
    if expected in kinds:
        return "hit"
    if expected in NO_MODEL:
        return "no_model"
    return "miss"


def result_for(run: dict[str, Any], scenario: str, event_id: str) -> dict[str, Any] | None:
    for row in reversed(run.get("results") or []):
        if not isinstance(row, dict):
            continue
        if row.get("scenario") == scenario and row.get("event_id") == event_id:
            return row
    return None


def _public_clip(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "scenario": item["scenario"],
        "event_id": item["event_id"],
        "camera_name": item.get("camera_name") or "",
        "created_at": item.get("created_at") or "",
        "size": int(item.get("size") or 0),
    }


def catalog(root: Path | None = None) -> dict[str, Any]:
    ensure_dirs(root)
    run = read_run(root)
    scenarios = []
    for item in SCENARIOS:
        clips = replay_clips(str(item["id"]))
        scenarios.append(
            {
                "id": item["id"],
                "label": item["label"],
                "hint": item["hint"],
                "ready": bool(item["ready"]),
                "videos": [_public_clip(clip) for clip in clips],
            }
        )
    if db_enabled():
        note = f"Последние {REPLAY_LIMIT} роликов каждого сценария из истории и MinIO"
    else:
        note = "База истории не настроена"
    return {
        "root": note,
        "run": run,
        "scenarios": scenarios,
    }
