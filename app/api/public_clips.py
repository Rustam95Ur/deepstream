"""Unauthenticated clip download for Campus ingest (HTTP GET video_url)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.db import db_enabled, session_scope
from app.ds.payload import clip_from_payload
from app.minio_store import get_minio_store
from app.models import TriggerEventRow

router = APIRouter(prefix="/api/v1/public", tags=["public"])


@router.get("/clips/{event_id}.mp4")
def public_clip(event_id: str) -> StreamingResponse:
    eid = event_id.strip().removesuffix(".mp4")
    if not eid:
        raise HTTPException(status_code=404, detail="Event not found")
    if not db_enabled():
        raise HTTPException(status_code=503, detail="Postgres is not configured")
    with session_scope(write=False) as session:
        row = session.scalar(
            select(TriggerEventRow).where(TriggerEventRow.event_id == eid)
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Event not found")
        clip = clip_from_payload(dict(row.payload or {}))
    key = clip["key"]
    if not key:
        raise HTTPException(status_code=404, detail="Clip not stored")
    store = get_minio_store()
    streamed = store.iter_object(key)
    if streamed is None:
        raise HTTPException(status_code=404, detail="Clip not found in storage")
    chunks, length = streamed
    headers = {
        "Content-Disposition": f'inline; filename="{eid}.mp4"',
        "Cache-Control": "private, max-age=3600",
    }
    if length > 0:
        headers["Content-Length"] = str(length)
    return StreamingResponse(chunks, media_type="video/mp4", headers=headers)
