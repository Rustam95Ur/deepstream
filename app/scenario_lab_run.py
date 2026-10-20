"""Play scenario-lab files through DeepStream and record which triggers fire.

The live pipeline is paused for the run and started again afterwards when it
was already on. Lab hits stay in ``run.json`` and are not sent to Campus.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from app.scenario_lab import (
    LabError,
    clips_for_run,
    empty_run,
    judge,
    lab_root,
    materialize_clip,
    read_run,
    utc_now,
    write_run,
)
from app.trigger_types import TRIGGER_TYPES

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_thread: threading.Thread | None = None
_cancel = threading.Event()
_shutdown = threading.Event()
_gpu_held = threading.Event()


def gpu_held() -> bool:
    """True while a lab file owns the DeepStream process."""
    return _gpu_held.is_set()


class _CollectSink:
    def __init__(self, source_video: str) -> None:
        self.source_video = source_video
        self.hits: list[dict[str, Any]] = []

    def send(self, payload: dict[str, Any]) -> str | None:
        offset = payload.get("source_offset_s")
        try:
            offset_s = float(offset) if offset is not None else None
        except (TypeError, ValueError):
            offset_s = None
        self.hits.append(
            {
                "trigger_type": str(payload.get("trigger_type") or ""),
                "offset_s": offset_s,
            }
        )
        return None


def lab_config(settings: Any, path: Any):
    from app.ds.config import CameraConfig, app_config_from_settings

    camera = CameraConfig(
        camera_id="lab",
        main_uri=path.resolve().as_uri(),
        enabled=True,
        name=path.name,
        enabled_triggers=frozenset(TRIGGER_TYPES),
    )
    cfg = app_config_from_settings(settings, [])
    cfg.cameras = [camera]
    cfg.pipeline.live_source = False
    cfg.trigger.enabled = frozenset(TRIGGER_TYPES)
    cfg.trigger.cooldown_s = 0.0
    tuned: dict[str, dict[str, Any]] = {}
    for kind, profile in (cfg.trigger.by_type or {}).items():
        row = dict(profile)
        row["cooldown_s"] = 0
        tuned[str(kind)] = row
    cfg.trigger.by_type = tuned
    return cfg, [camera]


def _file_max_s() -> float:
    raw = os.environ.get("SCENARIO_LAB_FILE_MAX_S", "1200") or "1200"
    try:
        return max(30.0, float(raw))
    except ValueError:
        return 1200.0


def _upsert(run: dict[str, Any], row: dict[str, Any]) -> None:
    key = (row.get("scenario"), row.get("event_id"))
    kept = [
        item
        for item in run.get("results") or []
        if (item.get("scenario"), item.get("event_id")) != key
    ]
    kept.append(row)
    run["results"] = kept


def _finish(run: dict[str, Any], status: str, error: str = "") -> None:
    run["status"] = status
    run["error"] = error
    run["finished_at"] = utc_now()
    run["current_file"] = ""
    run["current_event"] = ""
    run["current_scenario"] = ""
    write_run(run)


def running() -> bool:
    thread = _thread
    return bool(thread and thread.is_alive())


def start_run(scenario: str = "") -> dict[str, Any]:
    global _thread
    with _lock:
        if running():
            raise LabError(409, "прогон уже идёт")
        files = clips_for_run(scenario or "")
        if not files:
            raise LabError(400, "в истории нет роликов с файлом в MinIO")
        _cancel.clear()
        previous = read_run()
        selected = {(item["scenario"], item["event_id"]) for item in files}
        run = empty_run()
        run["status"] = "running"
        run["scenario"] = (scenario or "").strip().lower()
        run["started_at"] = utc_now()
        run["results"] = [
            row
            for row in previous.get("results") or []
            if isinstance(row, dict)
            and (row.get("scenario"), row.get("event_id")) not in selected
        ]
        write_run(run)
        _thread = threading.Thread(
            target=_loop,
            args=(list(files),),
            name="scenario-lab",
            daemon=True,
        )
        _thread.start()
    return read_run()


def cancel_run() -> dict[str, Any]:
    _cancel.set()
    return read_run()


def shutdown_run() -> None:
    _shutdown.set()
    _cancel.set()
    thread = _thread
    if thread and thread.is_alive():
        thread.join(timeout=8.0)


def _loop(files: list[dict[str, str]]) -> None:
    from app.billing import license_ok
    from app.storage import get_store
    from app.worker import get_manager

    run = read_run()
    manager = get_manager()
    was_running = manager.status().running
    run["paused_live"] = was_running
    write_run(run)
    try:
        if not license_ok():
            _finish(run, "error", "лицензия не активна")
            return
        ok, detail = _pipeline_ok()
        if not ok:
            _finish(run, "error", detail)
            return
        if was_running:
            manager.stop()
            if manager.thread_alive():
                _finish(run, "error", "живой разбор не остановился, прогон не начат")
                return
        _gpu_held.set()
        for item in files:
            if _cancel.is_set() or _shutdown.is_set():
                _finish(run, "cancelled")
                return
            scenario = str(item["scenario"])
            event_id = str(item["event_id"])
            run["current_scenario"] = scenario
            run["current_event"] = event_id
            run["current_file"] = str(item.get("camera_name") or event_id)
            write_run(run)
            row = _play_one(get_store().get_settings(), item)
            _upsert(run, row)
            write_run(run)
        if _cancel.is_set():
            _finish(run, "cancelled")
        else:
            _finish(run, "done")
    except Exception as exc:
        logger.exception("scenario lab failed")
        _finish(run, "error", str(exc) or "прогон остановился с ошибкой")
    finally:
        _gpu_held.clear()
        if was_running and not _shutdown.is_set() and not manager.thread_alive():
            try:
                manager.start()
            except Exception:
                logger.exception("scenario lab: failed to resume live pipeline")


def _pipeline_ok() -> tuple[bool, str]:
    try:
        import pyservicemaker  # noqa: F401

        return True, ""
    except Exception as exc:
        return False, f"DeepStream недоступен: {exc}"


def _play_one(settings: Any, item: dict[str, Any]) -> dict[str, Any]:
    from app.ds.pipeline import run_pipeline

    scenario = str(item.get("scenario") or "")
    event_id = str(item.get("event_id") or "")
    row: dict[str, Any] = {
        "scenario": scenario,
        "event_id": event_id,
        "camera_name": str(item.get("camera_name") or ""),
        "verdict": "error",
        "detected": [],
        "hits": [],
        "error": "",
        "finished_at": "",
    }
    owned = False
    path: Any = None
    try:
        path, owned = materialize_clip(item, lab_root() / "cache")
    except LabError as exc:
        row["error"] = exc.detail
        row["finished_at"] = utc_now()
        return row
    sink = _CollectSink(path.name)
    cfg, cameras = lab_config(settings, path)
    interrupt = threading.Event()
    stop_timer = threading.Event()

    def _watch() -> None:
        deadline = time.monotonic() + _file_max_s()
        while not stop_timer.wait(0.4):
            if _cancel.is_set() or time.monotonic() >= deadline:
                interrupt.set()
                return

    watcher = threading.Thread(target=_watch, name="scenario-lab-limit", daemon=True)
    watcher.start()
    try:
        run_pipeline(
            cfg,
            cameras,
            sink,
            exit_on_eos=True,
            interrupt=interrupt,
        )
    except Exception as exc:
        logger.exception("scenario lab file failed: %s/%s", scenario, event_id)
        row["error"] = str(exc) or "ролик не открылся"
        row["finished_at"] = utc_now()
        return row
    finally:
        stop_timer.set()
        if owned and path is not None:
            Path(path).unlink(missing_ok=True)
    detected: list[str] = []
    for hit in sink.hits:
        kind = str(hit.get("trigger_type") or "")
        if kind and kind not in detected:
            detected.append(kind)
    row["hits"] = sink.hits
    row["detected"] = detected
    if _cancel.is_set():
        row["verdict"] = "cancelled"
        row["error"] = "прогон остановлен"
    elif interrupt.is_set():
        row["verdict"] = "error"
        row["error"] = "ролик дольше лимита прогона"
    else:
        row["verdict"] = judge(scenario, detected)
    row["finished_at"] = utc_now()
    return row
