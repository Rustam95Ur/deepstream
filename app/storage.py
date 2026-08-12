"""Settings JSON + cameras/links in Postgres. Camera list is cached for the pipeline."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from app.db import session_scope
from app.models import CameraRow, LinkRow
from app.schemas import CameraIn, CameraOut
from app.settings import EnvBootstrap, NodeSettings, load_env_bootstrap

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _cache_ttl_s() -> float:
    raw = (os.environ.get("NEXUS_DS_CAMERA_CACHE_MS") or "").strip()
    ms = int(raw) if raw else 2000
    return max(0, ms) / 1000.0


def _camera_out(row: CameraRow) -> CameraOut:
    return CameraOut(
        id=row.id,
        name=row.name or "",
        main_uri=row.main_uri,
        enabled=bool(row.enabled),
        external_id=row.external_id or "",
        meta=row.extra or {},
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class Store:
    def __init__(self, data_dir: Path | None = None) -> None:
        boot = load_env_bootstrap()
        self.data_dir = Path(data_dir or boot.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.data_dir / "settings.json"
        self._lock = threading.RLock()
        self._settings = self._load_settings()
        self._cameras: list[CameraOut] | None = None
        self._cameras_at = 0.0
        self._sync_links(self._settings)

    def _load_settings(self) -> NodeSettings:
        if not self.settings_path.is_file():
            s = NodeSettings()
            self._write_json(self.settings_path, s.model_dump())
            return s
        raw = json.loads(self.settings_path.read_text(encoding="utf-8"))
        return NodeSettings.model_validate(raw or {})

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

    def _invalidate_cameras(self) -> None:
        self._cameras = None
        self._cameras_at = 0.0

    def _sync_links(self, settings: NodeSettings) -> None:
        values = {
            "cameras_url": settings.cameras_url,
            "triggers_url": settings.triggers_url,
        }
        now = _utcnow()
        try:
            with session_scope(write=True) as session:
                for kind, url in values.items():
                    row = session.get(LinkRow, kind)
                    if row is None:
                        session.add(
                            LinkRow(
                                kind=kind,
                                url=url or "",
                                enabled=bool((url or "").strip()),
                                updated_at=now,
                            )
                        )
                    else:
                        row.url = url or ""
                        row.enabled = bool((url or "").strip())
                        row.updated_at = now
        except Exception:
            logger.exception("failed to sync links")

    def get_settings(self) -> NodeSettings:
        with self._lock:
            return self._settings.model_copy(deep=True)

    def update_settings(self, patch: dict[str, Any]) -> NodeSettings:
        with self._lock:
            data = self._settings.model_dump()
            data.update({k: v for k, v in patch.items() if v is not None})
            self._settings = NodeSettings.model_validate(data)
            self._persist_settings()
            self._sync_links(self._settings)
            return self._settings.model_copy(deep=True)

    def list_cameras(self) -> list[CameraOut]:
        ttl = _cache_ttl_s()
        now = time.monotonic()
        with self._lock:
            if self._cameras is not None and (now - self._cameras_at) < ttl:
                return list(self._cameras)
        with session_scope(write=False) as session:
            rows = session.scalars(select(CameraRow).order_by(CameraRow.id)).all()
            out = [_camera_out(r) for r in rows]
        with self._lock:
            self._cameras = out
            self._cameras_at = time.monotonic()
            return list(out)

    def get_camera(self, camera_id: str) -> CameraOut | None:
        with session_scope(write=False) as session:
            row = session.get(CameraRow, camera_id)
            return _camera_out(row) if row else None

    def upsert_camera(self, data: CameraIn) -> tuple[CameraOut, bool]:
        now = _utcnow()
        with session_scope(write=True) as session:
            row = session.get(CameraRow, data.id)
            created = row is None
            if row is None:
                row = CameraRow(id=data.id, created_at=now)
                session.add(row)
            row.name = data.name
            row.main_uri = data.main_uri
            row.enabled = data.enabled
            row.external_id = data.external_id
            row.extra = data.meta or {}
            row.updated_at = now
            session.flush()
            out = _camera_out(row)
        with self._lock:
            self._invalidate_cameras()
        return out, created

    def delete_camera(self, camera_id: str) -> bool:
        with session_scope(write=True) as session:
            row = session.get(CameraRow, camera_id)
            if row is None:
                return False
            session.delete(row)
        with self._lock:
            self._invalidate_cameras()
        return True

    def replace_cameras(self, cameras: list[CameraIn]) -> list[CameraOut]:
        now = _utcnow()
        incoming = {c.id: c for c in cameras}
        with session_scope(write=True) as session:
            existing = {r.id: r for r in session.scalars(select(CameraRow)).all()}
            for cid, row in list(existing.items()):
                if cid not in incoming:
                    session.delete(row)
            out: list[CameraOut] = []
            for cam in cameras:
                row = existing.get(cam.id)
                if row is None:
                    row = CameraRow(id=cam.id, created_at=now)
                    session.add(row)
                row.name = cam.name
                row.main_uri = cam.main_uri
                row.enabled = cam.enabled
                row.external_id = cam.external_id
                row.extra = cam.meta or {}
                row.updated_at = now
                session.flush()
                out.append(_camera_out(row))
        with self._lock:
            self._invalidate_cameras()
        return out

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
