"""Cameras CRUD for the console and machine clients (Django / SmartBox-style)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api import CameraApiAuth, LicenseAuth
from app.schemas import (
    CameraIn,
    CameraListOut,
    CameraOut,
    CameraPatch,
    CameraTestBatchIn,
    CameraTestBatchOut,
)
from app.services import cameras as cameras_svc

router = APIRouter(
    prefix="/api/v1/cameras",
    tags=["cameras"],
    dependencies=[CameraApiAuth, LicenseAuth],
)


@router.get("", response_model=CameraListOut)
def list_cameras(
    q: str = Query(default=""),
    enabled: bool | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    cursor: str = Query(default=""),
    limit: int | None = Query(default=None, ge=1, le=200),
) -> CameraListOut:
    return cameras_svc.list_cameras(
        q=q,
        enabled=enabled,
        since=since,
        until=until,
        cursor=cursor,
        limit=limit,
    )


@router.post(
    "/test-batch",
    response_model=CameraTestBatchOut,
    status_code=status.HTTP_201_CREATED,
)
def create_test_cameras(body: CameraTestBatchIn) -> CameraTestBatchOut:
    return cameras_svc.create_test_batch(main_uri=body.main_uri, count=body.count)


@router.get("/{camera_id}", response_model=CameraOut)
def get_camera(camera_id: str) -> CameraOut:
    return cameras_svc.get_camera(camera_id)


@router.post("", response_model=CameraOut)
def create_or_upsert_camera(body: CameraIn, response: Response) -> CameraOut:
    cam, created = cameras_svc.upsert_camera(body)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return cam


@router.put("/{camera_id}", response_model=CameraOut)
def upsert_camera(camera_id: str, body: CameraIn, response: Response) -> CameraOut:
    if body.id and body.id != camera_id:
        raise HTTPException(status_code=400, detail="id mismatch")
    cam, created = cameras_svc.upsert_camera(body, camera_id=camera_id)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return cam


@router.patch("/{camera_id}", response_model=CameraOut)
def patch_camera(camera_id: str, body: CameraPatch) -> CameraOut:
    return cameras_svc.patch_camera(camera_id, body)


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_camera(camera_id: str) -> None:
    cameras_svc.delete_camera(camera_id)
