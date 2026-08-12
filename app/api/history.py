"""History of triggers and outbound sends."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api import ApiAuth
from app.db import db_enabled, session_scope
from app.models import SendEventRow, TriggerEventRow
from app.schemas import SendEventOut, TriggerEventOut

router = APIRouter(prefix="/api/v1/history", tags=["history"], dependencies=[ApiAuth])


def _require_db() -> None:
    if not db_enabled():
        raise HTTPException(status_code=503, detail="Postgres is not configured")


@router.get("/triggers", response_model=list[TriggerEventOut])
def list_triggers(limit: int = Query(default=100, ge=1, le=500)) -> list[TriggerEventOut]:
    _require_db()
    with session_scope(write=False) as session:
        rows = session.scalars(
            select(TriggerEventRow).order_by(TriggerEventRow.created_at.desc()).limit(limit)
        ).all()
        return [
            TriggerEventOut(
                event_id=r.event_id,
                camera_id=r.camera_id,
                trigger_type=r.trigger_type,
                category=r.category,
                evidence=r.evidence or {},
                created_at=r.created_at,
            )
            for r in rows
        ]


@router.get("/sends", response_model=list[SendEventOut])
def list_sends(limit: int = Query(default=100, ge=1, le=500)) -> list[SendEventOut]:
    _require_db()
    with session_scope(write=False) as session:
        rows = session.scalars(
            select(SendEventRow).order_by(SendEventRow.created_at.desc()).limit(limit)
        ).all()
        return [
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
        ]
