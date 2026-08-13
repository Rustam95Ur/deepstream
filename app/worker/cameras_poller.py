"""Optional pull of cameras from cameras_url."""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
from typing import Any

from app.schemas import CameraIn
from app.storage import Store, get_store
from app.worker import get_manager

logger = logging.getLogger(__name__)


def _parse_cameras_payload(data: Any) -> list[CameraIn]:
    if isinstance(data, dict):
        items = data.get("cameras") or data.get("items") or []
    elif isinstance(data, list):
        items = data
    else:
        items = []
    out: list[CameraIn] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        cam_id = str(item.get("id") or item.get("camera_id") or "").strip()
        uri = str(item.get("main_uri") or item.get("uri") or item.get("rtsp_url") or "").strip()
        if not cam_id or not uri:
            continue
        out.append(
            CameraIn(
                id=cam_id,
                name=str(item.get("name") or cam_id),
                main_uri=uri,
                enabled=bool(item.get("enabled", True)),
                external_id=str(item.get("external_id") or ""),
                meta={k: v for k, v in item.items() if k not in {
                    "id", "camera_id", "name", "main_uri", "uri", "rtsp_url",
                    "enabled", "external_id",
                }},
            )
        )
    return out


def fetch_cameras_from_url(url: str, *, token: str = "", timeout: float = 15.0) -> list[CameraIn]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "nexus-deepstream/0.1", "Accept": "application/json"},
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    data = json.loads(raw)
    return _parse_cameras_payload(data)


class CamerasPoller:
    def __init__(self, store: Store | None = None) -> None:
        self.store = store or get_store()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="cameras-poller", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def sync_once(self) -> int:
        settings = self.store.get_settings()
        url = settings.cameras_url.strip()
        if not url:
            return 0
        cams = fetch_cameras_from_url(url, token=settings.api_token)
        before = {c.id for c in self.store.list_cameras()}
        self.store.replace_cameras(cams)
        after = {c.id for c in cams}
        if before != after:
            get_manager().request_reload()
            from app.ds.ring_buffer import get_ring_buffer

            get_ring_buffer().request_refresh()
        logger.info("Pulled %s cameras from %s", len(cams), url)
        return len(cams)

    def _loop(self) -> None:
        while not self._stop.is_set():
            settings = self.store.get_settings()
            poll = int(settings.cameras_poll_sec or 0)
            if settings.cameras_url.strip() and poll > 0:
                try:
                    self.sync_once()
                except Exception:
                    logger.exception("cameras_url poll failed")
                self._stop.wait(poll)
            else:
                self._stop.wait(5.0)


_poller: CamerasPoller | None = None


def get_poller() -> CamerasPoller:
    global _poller
    if _poller is None:
        _poller = CamerasPoller()
    return _poller
