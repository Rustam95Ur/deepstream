"""Camera registry service: capacity, CRUD helpers, pipeline reload."""

from __future__ import annotations

import logging
import time
from datetime import datetime

from fastapi import HTTPException

from app.paging import cursor_id, cursor_or_400
from app.schemas import (
    CameraIn,
    CameraListOut,
    CameraOut,
    CameraPatch,
    CameraTestBatchOut,
)
from app.storage import Store, get_store
from app.timeutil import aware
from app.video_client import notify_reload, worker_status

logger = logging.getLogger(__name__)

TEST_META = {
    "test": True,
    "stream_protocol": 2,
    "resolution_width": 1280,
    "resolution_height": 720,
    "fps": 25,
    "allow_preprocessing": False,
    "usage_modules": [2],
}


def with_id(store: Store, body: CameraIn, *, camera_id: str = "") -> CameraIn:
    cam_id = (
        camera_id or body.id or body.external_id or ""
    ).strip() or store.new_camera_id()
    return body.model_copy(update={"id": cam_id, "name": body.name or cam_id})


def guard_capacity(store: Store, new_ids: set[str]) -> None:
    settings = store.get_settings()
    existing = {c.id for c in store.list_cameras()}
    if len(existing | new_ids) > settings.max_streams:
        raise HTTPException(
            status_code=400,
            detail=f"max_streams={settings.max_streams} reached",
        )


def alloc_test_ids(existing_ids: set[str], count: int) -> list[str]:
    ids: list[str] = []
    n = 1
    while len(ids) < count:
        cam_id = f"test_{n}"
        if cam_id not in existing_ids:
            ids.append(cam_id)
        n += 1
        if n > 10_000:
            raise HTTPException(
                status_code=400, detail="cannot allocate test camera ids"
            )
    return ids


def reload_pipeline_drop_camera(camera_id: str) -> None:
    """Reload video worker and wait until ``camera_id`` leaves the live set."""
    status = notify_reload()
    if status is None:
        logger.warning(
            "camera %s removed from DB, but video reload failed "
            "(check NEXUS_DS_VIDEO_URL) — old source may linger until config watch",
            camera_id,
        )
        return
    st = status
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        st = worker_status()
        ids = set(st.camera_ids or [])
        if camera_id not in ids and not st.reload_pending:
            logger.info(
                "camera %s removed from pipeline (%s cams left)",
                camera_id,
                len(ids),
            )
            return
        time.sleep(0.4)
    logger.warning(
        "camera %s removed from DB; pipeline still reloading after 15s "
        "(camera_ids=%s reload_pending=%s)",
        camera_id,
        list(st.camera_ids or []),
        st.reload_pending,
    )


def list_cameras(
    *,
    q: str = "",
    enabled: bool | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    cursor: str = "",
    limit: int | None = None,
) -> CameraListOut:
    store = get_store()
    settings = store.get_settings()
    payload = cursor_or_400(cursor)
    after_id = after_name = None
    if payload is not None:
        after_id = cursor_id(payload)
        after_name = str(payload.get("k") or "") if "k" in payload else None
    paginated = limit is not None or after_id is not None
    page_size = (limit or 10) if paginated else None
    filtered = (
        bool(q.strip()) or enabled is not None or since is not None or until is not None
    )
    next_cursor = None
    if paginated or filtered:
        cams, next_cursor = store.search_cameras(
            q=q,
            enabled=enabled,
            since=aware(since),
            until=aware(until),
            after_name=after_name,
            after_id=after_id,
            limit=page_size,
        )
    else:
        cams = store.list_cameras()
    updated = None
    if cams:
        updated = max(c.updated_at for c in cams)
    return CameraListOut(
        node_id=settings.node_id,
        cameras=cams,
        updated_at=updated,
        next_cursor=next_cursor,
    )


def create_test_batch(*, main_uri: str, count: int) -> CameraTestBatchOut:
    uri = main_uri.strip()
    low = uri.lower()
    if not (low.startswith("rtsp://") or low.startswith("file://")):
        raise HTTPException(status_code=400, detail="нужна ссылка rtsp:// или file://")
    store = get_store()
    settings = store.get_settings()
    existing = {c.id for c in store.list_cameras()}
    free = settings.max_streams - len(existing)
    if count > max(0, free):
        raise HTTPException(
            status_code=400,
            detail=(
                f"max_streams={settings.max_streams}, "
                f"свободно слотов: {max(0, free)}"
            ),
        )
    ids = alloc_test_ids(existing, count)
    guard_capacity(store, set(ids))
    payloads = [
        CameraIn(
            id=cam_id,
            name=f"Тест {cam_id.split('_', 1)[1]}",
            main_uri=uri,
            enabled=True,
            meta=dict(TEST_META),
            enabled_triggers=None,
        )
        for cam_id in ids
    ]
    cams, created_n, _updated_n = store.upsert_many(payloads)
    notify_reload()
    return CameraTestBatchOut(cameras=cams, created=created_n)


def get_camera(camera_id: str) -> CameraOut:
    cam = get_store().get_camera(camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    return cam


def upsert_camera(
    body: CameraIn, *, camera_id: str = ""
) -> tuple[CameraOut, bool]:
    """Return ``(camera, created)``."""
    store = get_store()
    payload = with_id(store, body, camera_id=camera_id)
    guard_capacity(store, {payload.id})
    cam, created = store.upsert_camera(payload)
    notify_reload()
    return cam, created


def patch_camera(camera_id: str, body: CameraPatch) -> CameraOut:
    patch = body.model_dump(exclude_unset=True)
    cam = get_store().patch_camera(camera_id, patch)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    if "enabled" in patch and not cam.enabled:
        reload_pipeline_drop_camera(camera_id)
    else:
        notify_reload()
    return cam


def delete_camera(camera_id: str) -> None:
    if not get_store().delete_camera(camera_id):
        raise HTTPException(status_code=404, detail="Camera not found")
    reload_pipeline_drop_camera(camera_id)
