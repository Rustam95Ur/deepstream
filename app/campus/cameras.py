"""Resolve DeepStream camera id for Campus channel_info (no DB in ingest)."""

from __future__ import annotations

import logging
from typing import Protocol

from app.ds.payload import ipc_addr_from_uri

logger = logging.getLogger(__name__)


def _str(value: object) -> str:
    return str(value or "").strip()


class CameraLike(Protocol):
    id: str
    name: str
    external_id: str
    main_uri: str


class CameraResolver(Protocol):
    def resolve_id(self, *, channel_name: str = "", ipc_addr: str = "") -> str:
        """Return local camera id or empty if not uniquely matched."""


class StoreCameraResolver:
    """Lookup via ``Store.list_cameras()`` (name / id / RTSP ipc_addr)."""

    def resolve_id(self, *, channel_name: str = "", ipc_addr: str = "") -> str:
        name = _str(channel_name)
        ipc = _str(ipc_addr)
        if not name and not ipc:
            return ""
        try:
            from app.storage import get_store

            cameras = get_store().list_cameras()
        except Exception:
            logger.exception("channel_id lookup: failed to list local cameras")
            return ""
        return resolve_camera_id(cameras, channel_name=name, ipc_addr=ipc)


def resolve_camera_id(
    cameras: list[CameraLike],
    *,
    channel_name: str = "",
    ipc_addr: str = "",
) -> str:
    """Pure match helper — easy to unit-test without Postgres."""
    name = _str(channel_name)
    ipc = _str(ipc_addr)
    if not name and not ipc:
        return ""

    by_id: list[str] = []
    by_name: list[str] = []
    by_ipc: list[str] = []
    for cam in cameras:
        cam_id = _str(getattr(cam, "id", None))
        if not cam_id:
            continue
        cam_name = _str(getattr(cam, "name", None))
        cam_ext = _str(getattr(cam, "external_id", None))
        if name and (cam_id == name or cam_ext == name):
            by_id.append(cam_id)
        if name and cam_name == name:
            by_name.append(cam_id)
        if ipc:
            derived = ipc_addr_from_uri(_str(getattr(cam, "main_uri", None)))
            if derived and derived == ipc:
                by_ipc.append(cam_id)
    for group in (by_id, by_name, by_ipc):
        uniq = list(dict.fromkeys(group))
        if len(uniq) == 1:
            logger.info(
                "channel_id recovered from local cameras name=%r ipc=%r → %s",
                name,
                ipc,
                uniq[0],
            )
            return uniq[0]
    return ""


_resolver: CameraResolver | None = None


def get_camera_resolver() -> CameraResolver:
    global _resolver
    if _resolver is None:
        _resolver = StoreCameraResolver()
    return _resolver


def set_camera_resolver(resolver: CameraResolver | None) -> None:
    """Override resolver (tests / offline). ``None`` restores Store default."""
    global _resolver
    _resolver = resolver
