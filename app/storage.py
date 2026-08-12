"""JSON file persistence for settings + cameras."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.schemas import CameraIn, CameraOut
from app.settings import EnvBootstrap, NodeSettings, load_env_bootstrap


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    def __init__(self, data_dir: Path | None = None) -> None:
        boot = load_env_bootstrap()
        self.data_dir = Path(data_dir or boot.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.data_dir / "settings.json"
        self.cameras_path = self.data_dir / "cameras.json"
        self._lock = threading.RLock()
        self._settings = self._load_settings()
        self._cameras = self._load_cameras()

    def _load_settings(self) -> NodeSettings:
        if not self.settings_path.is_file():
            s = NodeSettings()
            self._write_json(self.settings_path, s.model_dump())
            return s
        raw = json.loads(self.settings_path.read_text(encoding="utf-8"))
        return NodeSettings.model_validate(raw or {})

    def _load_cameras(self) -> dict[str, dict[str, Any]]:
        if not self.cameras_path.is_file():
            self._write_json(self.cameras_path, {"cameras": []})
            return {}
        raw = json.loads(self.cameras_path.read_text(encoding="utf-8"))
        items = raw.get("cameras") if isinstance(raw, dict) else []
        out: dict[str, dict[str, Any]] = {}
        for item in items or []:
            if not isinstance(item, dict):
                continue
            cid = str(item.get("id") or "").strip()
            if not cid:
                continue
            out[cid] = item
        return out

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        tmp.replace(path)

    def _persist_settings(self) -> None:
        self._write_json(self.settings_path, self._settings.model_dump())

    def _persist_cameras(self) -> None:
        cams = sorted(self._cameras.values(), key=lambda c: str(c.get("id") or ""))
        self._write_json(
            self.cameras_path,
            {"cameras": cams, "updated_at": _utcnow().isoformat()},
        )

    # --- settings ---

    def get_settings(self) -> NodeSettings:
        with self._lock:
            return self._settings.model_copy(deep=True)

    def update_settings(self, patch: dict[str, Any]) -> NodeSettings:
        with self._lock:
            data = self._settings.model_dump()
            data.update({k: v for k, v in patch.items() if v is not None})
            self._settings = NodeSettings.model_validate(data)
            self._persist_settings()
            return self._settings.model_copy(deep=True)

    # --- cameras ---

    def list_cameras(self) -> list[CameraOut]:
        with self._lock:
            return [CameraOut.model_validate(c) for c in self._cameras.values()]

    def get_camera(self, camera_id: str) -> CameraOut | None:
        with self._lock:
            raw = self._cameras.get(camera_id)
            return CameraOut.model_validate(raw) if raw else None

    def upsert_camera(self, data: CameraIn) -> tuple[CameraOut, bool]:
        """Returns (camera, created)."""
        with self._lock:
            now = _utcnow()
            existing = self._cameras.get(data.id)
            created = existing is None
            if existing:
                created_at = existing.get("created_at") or now.isoformat()
            else:
                created_at = now.isoformat()
            row = {
                **data.model_dump(),
                "created_at": created_at,
                "updated_at": now.isoformat(),
            }
            self._cameras[data.id] = row
            self._persist_cameras()
            return CameraOut.model_validate(row), created

    def delete_camera(self, camera_id: str) -> bool:
        with self._lock:
            if camera_id not in self._cameras:
                return False
            del self._cameras[camera_id]
            self._persist_cameras()
            return True

    def replace_cameras(self, cameras: list[CameraIn]) -> list[CameraOut]:
        """Full replace (used by poll from cameras_url)."""
        with self._lock:
            now = _utcnow()
            new_map: dict[str, dict[str, Any]] = {}
            for cam in cameras:
                prev = self._cameras.get(cam.id)
                created_at = (
                    (prev or {}).get("created_at") if prev else None
                ) or now.isoformat()
                new_map[cam.id] = {
                    **cam.model_dump(),
                    "created_at": created_at,
                    "updated_at": now.isoformat(),
                }
            self._cameras = new_map
            self._persist_cameras()
            return [CameraOut.model_validate(c) for c in new_map.values()]

    def new_camera_id(self) -> str:
        return f"cam_{uuid4().hex[:12]}"


_store: Store | None = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store


def get_bootstrap() -> EnvBootstrap:
    return load_env_bootstrap()
