"""Cameras CRUD — Django can pull/push like SmartBox channels."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, status

from app.api import ApiAuth
from app.paging import cursor_id, cursor_or_400
from app.schemas import CameraIn, CameraListOut, CameraOut
from app.storage import get_store
from app.worker import get_manager

router = APIRouter(prefix="/api/v1/cameras", tags=["cameras"], dependencies=[ApiAuth])


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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
    after_id = cursor_id(cursor_or_400(cursor))
    paginated = limit is not None or after_id is not None
    page_size = (limit or 25) if paginated else None
    filtered = bool(q.strip()) or enabled is not None or since is not None or until is not None
    next_cursor = None
    if paginated or filtered:
        cams, next_cursor = store.search_cameras(
            q=q,
            enabled=enabled,
            since=_aware(since),
            until=_aware(until),
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


@router.get("/{camera_id}", response_model=CameraOut)
def get_camera(camera_id: str) -> CameraOut:
    cam = get_store().get_camera(camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    return cam


@router.post("", response_model=CameraOut, status_code=status.HTTP_201_CREATED)
def create_or_upsert_camera(body: CameraIn) -> CameraOut:
    store = get_store()
    settings = store.get_settings()
    cams = store.list_cameras()
    if body.id not in {c.id for c in cams} and len(cams) >= settings.max_streams:
        raise HTTPException(
            status_code=400,
            detail=f"max_streams={settings.max_streams} reached",
        )
    cam, _created = store.upsert_camera(body)
    get_manager().request_reload()
    return cam


@router.put("/{camera_id}", response_model=CameraOut)
def update_camera(camera_id: str, body: CameraIn) -> CameraOut:
    if body.id != camera_id:
        raise HTTPException(status_code=400, detail="id mismatch")
    store = get_store()
    if not store.get_camera(camera_id):
        raise HTTPException(status_code=404, detail="Camera not found")
    cam, _ = store.upsert_camera(body)
    get_manager().request_reload()
    return cam


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_camera(camera_id: str) -> None:
    if not get_store().delete_camera(camera_id):
        raise HTTPException(status_code=404, detail="Camera not found")
    get_manager().request_reload()
