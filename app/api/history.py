"""History of triggers, outbound sends, and webhook jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, tuple_

from app.api import ApiAuth
from app.db import db_enabled, session_scope
from app.ds.payload import clip_from_payload, normalize_payload
from app.minio_store import get_minio_store
from app.models import OutboundJobRow, SendEventRow, TriggerEventRow
from app.paging import cursor_or_400, cursor_str, cursor_time, encode_cursor
from app.schemas import (
    ClipOut,
    ClipUrlOut,
    OutboundJobListOut,
    OutboundJobOut,
    ResendOut,
    SendEventOut,
    SendHistoryOut,
    TriggerEventDetailOut,
    TriggerEventOut,
    TriggerHistoryOut,
)
from app.webhooks import resend_event, retry_job

router = APIRouter(prefix="/api/v1/history", tags=["history"], dependencies=[ApiAuth])


def _require_db() -> None:
    if not db_enabled():
        raise HTTPException(status_code=503, detail="Postgres is not configured")


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _after_key(cursor: str):
    payload = cursor_or_400(cursor)
    if payload is None:
        return None
    return cursor_time(payload), cursor_str(payload, "id")


def _clip_out(payload: dict[str, Any]) -> ClipOut:
    clip = clip_from_payload(payload)
    return ClipOut(url=clip["url"], bucket=clip["bucket"], key=clip["key"])


def _trigger_out(row: TriggerEventRow) -> TriggerEventOut:
    payload = dict(row.payload or {})
    clip = _clip_out(payload)
    return TriggerEventOut(
        event_id=row.event_id,
        camera_id=row.camera_id,
        camera_name=str(payload.get("camera_name") or ""),
        trigger_type=row.trigger_type,
        category=row.category,
        evidence=row.evidence or {},
        clip=clip,
        video_url=clip.url,
        video_bucket=clip.bucket,
        video_key=clip.key,
        created_at=row.created_at,
    )


def _job_out(row: OutboundJobRow) -> OutboundJobOut:
    return OutboundJobOut(
        id=row.id,
        event_id=row.event_id,
        webhook_id=row.webhook_id,
        url=row.url,
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        status=row.status,
        last_error=row.last_error or "",
        http_status=row.http_status,
        next_attempt_at=row.next_attempt_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/triggers", response_model=TriggerHistoryOut)
def list_triggers(
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str = Query(default=""),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    camera_id: str = Query(default=""),
    trigger_type: str = Query(default=""),
    category: str = Query(default=""),
    event_id: str = Query(default=""),
) -> TriggerHistoryOut:
    _require_db()
    stmt = select(TriggerEventRow)
    camera = camera_id.strip()
    kind = trigger_type.strip()
    cat = category.strip()
    eid = event_id.strip()
    start = _aware(since)
    end = _aware(until)
    if camera:
        stmt = stmt.where(TriggerEventRow.camera_id == camera)
    if kind:
        stmt = stmt.where(TriggerEventRow.trigger_type == kind)
    if cat:
        stmt = stmt.where(TriggerEventRow.category == cat)
    if eid:
        stmt = stmt.where(TriggerEventRow.event_id.ilike(f"%{eid}%"))
    if start is not None:
        stmt = stmt.where(TriggerEventRow.created_at >= start)
    if end is not None:
        stmt = stmt.where(TriggerEventRow.created_at <= end)
    key = _after_key(cursor)
    if key is not None:
        stmt = stmt.where(tuple_(TriggerEventRow.created_at, TriggerEventRow.id) < key)
    stmt = stmt.order_by(TriggerEventRow.created_at.desc(), TriggerEventRow.id.desc()).limit(limit + 1)
    with session_scope(write=False) as session:
        rows = list(session.scalars(stmt).all())
        extra = len(rows) > limit
        if extra:
            rows = rows[:limit]
        next_cursor = encode_cursor(t=rows[-1].created_at.isoformat(), id=rows[-1].id) if extra and rows else None
        items = [_trigger_out(r) for r in rows]
    return TriggerHistoryOut(items=items, next_cursor=next_cursor)


@router.get("/triggers/{event_id}", response_model=TriggerEventDetailOut)
def get_trigger(event_id: str) -> TriggerEventDetailOut:
    _require_db()
    with session_scope(write=False) as session:
        row = session.scalar(select(TriggerEventRow).where(TriggerEventRow.event_id == event_id.strip()))
        if row is None:
            raise HTTPException(status_code=404, detail="Event not found")
        base = _trigger_out(row)
        payload = normalize_payload(dict(row.payload or {}))
    return TriggerEventDetailOut(**base.model_dump(), payload=payload)


@router.get("/triggers/{event_id}/clip", response_model=ClipUrlOut)
def get_trigger_clip(event_id: str) -> ClipUrlOut:
    _require_db()
    with session_scope(write=False) as session:
        row = session.scalar(select(TriggerEventRow).where(TriggerEventRow.event_id == event_id.strip()))
        if row is None:
            raise HTTPException(status_code=404, detail="Event not found")
        clip = clip_from_payload(dict(row.payload or {}))
    url = clip["url"]
    if clip["key"]:
        url = get_minio_store().object_url(clip["key"]) or url
    return ClipUrlOut(event_id=event_id, url=url, bucket=clip["bucket"], key=clip["key"])


@router.post("/triggers/{event_id}/resend", response_model=ResendOut)
def post_trigger_resend(event_id: str) -> ResendOut:
    _require_db()
    with session_scope(write=False) as session:
        row = session.scalar(select(TriggerEventRow).where(TriggerEventRow.event_id == event_id.strip()))
        if row is None:
            raise HTTPException(status_code=404, detail="Event not found")
    queued = resend_event(event_id.strip())
    return ResendOut(event_id=event_id.strip(), queued=queued)


@router.get("/sends", response_model=SendHistoryOut)
def list_sends(
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str = Query(default=""),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    status: str = Query(default=""),
    event_id: str = Query(default=""),
    sink: str = Query(default=""),
) -> SendHistoryOut:
    _require_db()
    stmt = select(SendEventRow)
    st = status.strip()
    eid = event_id.strip()
    snk = sink.strip()
    start = _aware(since)
    end = _aware(until)
    if st:
        stmt = stmt.where(SendEventRow.status == st)
    if eid:
        stmt = stmt.where(SendEventRow.event_id.ilike(f"%{eid}%"))
    if snk:
        stmt = stmt.where(SendEventRow.sink == snk)
    if start is not None:
        stmt = stmt.where(SendEventRow.created_at >= start)
    if end is not None:
        stmt = stmt.where(SendEventRow.created_at <= end)
    key = _after_key(cursor)
    if key is not None:
        stmt = stmt.where(tuple_(SendEventRow.created_at, SendEventRow.id) < key)
    stmt = stmt.order_by(SendEventRow.created_at.desc(), SendEventRow.id.desc()).limit(limit + 1)
    with session_scope(write=False) as session:
        rows = list(session.scalars(stmt).all())
        extra = len(rows) > limit
        if extra:
            rows = rows[:limit]
        next_cursor = encode_cursor(t=rows[-1].created_at.isoformat(), id=rows[-1].id) if extra and rows else None
        items = [
            SendEventOut(
                id=r.id,
                event_id=r.event_id,
                sink=r.sink,
                url=r.url,
                status=r.status,
                http_status=r.http_status,
                error=r.error or "",
                created_at=r.created_at,
            )
            for r in rows
        ]
    return SendHistoryOut(items=items, next_cursor=next_cursor)


@router.get("/outbound", response_model=OutboundJobListOut)
def list_outbound(
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str = Query(default=""),
    status: str = Query(default=""),
    event_id: str = Query(default=""),
) -> OutboundJobListOut:
    _require_db()
    stmt = select(OutboundJobRow)
    st = status.strip()
    eid = event_id.strip()
    if st:
        stmt = stmt.where(OutboundJobRow.status == st)
    if eid:
        stmt = stmt.where(OutboundJobRow.event_id.ilike(f"%{eid}%"))
    key = _after_key(cursor)
    if key is not None:
        stmt = stmt.where(tuple_(OutboundJobRow.updated_at, OutboundJobRow.id) < key)
    stmt = stmt.order_by(OutboundJobRow.updated_at.desc(), OutboundJobRow.id.desc()).limit(limit + 1)
    with session_scope(write=False) as session:
        rows = list(session.scalars(stmt).all())
        extra = len(rows) > limit
        if extra:
            rows = rows[:limit]
        next_cursor = (
            encode_cursor(t=rows[-1].updated_at.isoformat(), id=rows[-1].id) if extra and rows else None
        )
        items = [_job_out(r) for r in rows]
    return OutboundJobListOut(items=items, next_cursor=next_cursor)


@router.post("/outbound/{job_id}/retry", response_model=OutboundJobOut)
def post_outbound_retry(job_id: str) -> OutboundJobOut:
    _require_db()
    row = retry_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_out(row)
