"""Cameras CRUD — Django can pull/push like SmartBox channels."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api import ApiAuth
from app.schemas import CameraIn, CameraListOut, CameraOut
from app.storage import get_store
from app.worker import get_manager

router = APIRouter(prefix="/api/v1/cameras", tags=["cameras"], dependencies=[ApiAuth])


@router.get("", response_model=CameraListOut)
def list_cameras() -> CameraListOut:
    store = get_store()
    settings = store.get_settings()
    cams = store.list_cameras()
    updated = None
    if cams:
        updated = max(c.updated_at for c in cams)
    return CameraListOut(
        node_id=settings.node_id,
        cameras=cams,
        updated_at=updated,
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
