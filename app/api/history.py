"""History of triggers and outbound sends."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select, tuple_

from app.api import ApiAuth
from app.db import db_enabled, session_scope
from app.models import SendEventRow, TriggerEventRow
from app.paging import cursor_or_400, cursor_str, cursor_time, encode_cursor
from app.schemas import SendEventOut, SendHistoryOut, TriggerEventOut, TriggerHistoryOut

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
    return TriggerHistoryOut(
        items=[
            TriggerEventOut(
                event_id=r.event_id,
                camera_id=r.camera_id,
                trigger_type=r.trigger_type,
                category=r.category,
                evidence=r.evidence or {},
                created_at=r.created_at,
            )
            for r in rows
        ],
        next_cursor=next_cursor,
    )


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
    return SendHistoryOut(
        items=[
            SendEventOut(
                event_id=r.event_id,
                sink=r.sink,
                url=r.url,
                status=r.status,
                http_status=r.http_status,
                error=r.error or "",
                created_at=r.created_at,
            )
            for r in rows
        ],
        next_cursor=next_cursor,
    )
