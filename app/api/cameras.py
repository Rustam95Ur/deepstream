"""Cameras CRUD for the console and machine clients (Django / SmartBox-style)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api import CameraApiAuth, LicenseAuth
from app.paging import cursor_id, cursor_or_400
from app.schemas import (
    CameraIn,
    CameraListOut,
    CameraOut,
    CameraPatch,
    CameraTestBatchIn,
    CameraTestBatchOut,
)
from app.storage import Store, get_store
from app.video_client import notify_reload

_TEST_META = {
    "test": True,
    "stream_protocol": 2,
    "resolution_width": 1280,
    "resolution_height": 720,
    "fps": 25,
    "allow_preprocessing": False,
    "usage_modules": [2],
}

router = APIRouter(
    prefix="/api/v1/cameras",
    tags=["cameras"],
    dependencies=[CameraApiAuth, LicenseAuth],
)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _with_id(store: Store, body: CameraIn, *, camera_id: str = "") -> CameraIn:
    cam_id = (
        camera_id or body.id or body.external_id or ""
    ).strip() or store.new_camera_id()
    return body.model_copy(update={"id": cam_id, "name": body.name or cam_id})


def _guard_capacity(store: Store, new_ids: set[str]) -> None:
    settings = store.get_settings()
    existing = {c.id for c in store.list_cameras()}
    if len(existing | new_ids) > settings.max_streams:
        raise HTTPException(
            status_code=400,
            detail=f"max_streams={settings.max_streams} reached",
        )


def _alloc_test_ids(existing_ids: set[str], count: int) -> list[str]:
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


@router.get("", response_model=CameraListOut)
def list_cameras(
    q: str = Query(default=""),
    enabled: bool | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    cursor: str = Query(default=""),
    limit: int | None = Query(default=None, ge=1, le=200),
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
            since=_aware(since),
            until=_aware(until),
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


@router.post(
    "/test-batch",
    response_model=CameraTestBatchOut,
    status_code=status.HTTP_201_CREATED,
)
def create_test_cameras(body: CameraTestBatchIn) -> CameraTestBatchOut:
    uri = body.main_uri.strip()
    low = uri.lower()
    if not (low.startswith("rtsp://") or low.startswith("file://")):
        raise HTTPException(status_code=400, detail="нужна ссылка rtsp:// или file://")
    store = get_store()
    settings = store.get_settings()
    existing = {c.id for c in store.list_cameras()}
    free = settings.max_streams - len(existing)
    if body.count > max(0, free):
        raise HTTPException(
            status_code=400,
            detail=f"max_streams={settings.max_streams}, свободно слотов: {max(0, free)}",
        )
    ids = _alloc_test_ids(existing, body.count)
    _guard_capacity(store, set(ids))
    payloads = [
        CameraIn(
            id=cam_id,
            name=f"Тест {cam_id.split('_', 1)[1]}",
            main_uri=uri,
            enabled=True,
            meta=dict(_TEST_META),
            enabled_triggers=None,
        )
        for cam_id in ids
    ]
    cams, created_n, _updated_n = store.upsert_many(payloads)
    notify_reload()
    return CameraTestBatchOut(cameras=cams, created=created_n)


@router.get("/{camera_id}", response_model=CameraOut)
def get_camera(camera_id: str) -> CameraOut:
    cam = get_store().get_camera(camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    return cam


@router.post("", response_model=CameraOut)
def create_or_upsert_camera(body: CameraIn, response: Response) -> CameraOut:
    store = get_store()
    payload = _with_id(store, body)
    _guard_capacity(store, {payload.id})
    cam, created = store.upsert_camera(payload)
    notify_reload()
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return cam


@router.put("/{camera_id}", response_model=CameraOut)
def upsert_camera(camera_id: str, body: CameraIn, response: Response) -> CameraOut:
    if body.id and body.id != camera_id:
        raise HTTPException(status_code=400, detail="id mismatch")
    store = get_store()
    payload = _with_id(store, body, camera_id=camera_id)
    _guard_capacity(store, {payload.id})
    cam, created = store.upsert_camera(payload)
    notify_reload()
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return cam


@router.patch("/{camera_id}", response_model=CameraOut)
def patch_camera(camera_id: str, body: CameraPatch) -> CameraOut:
    patch = body.model_dump(exclude_unset=True)
    cam = get_store().patch_camera(camera_id, patch)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    notify_reload()
    return cam


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_camera(camera_id: str) -> None:
    if not get_store().delete_camera(camera_id):
        raise HTTPException(status_code=404, detail="Camera not found")
    notify_reload()
