"""History of triggers, outbound sends, and webhook jobs."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query

from app.api import ApiAuth, LicenseAuth
from app.schemas import (
    ClipUrlOut,
    OutboundJobListOut,
    OutboundJobOut,
    ResendOut,
    SendHistoryOut,
    TriggerEventDetailOut,
    TriggerHistoryOut,
)
from app.services import history as history_svc

router = APIRouter(
    prefix="/api/v1/history",
    tags=["history"],
    dependencies=[ApiAuth, LicenseAuth],
)


@router.get("/triggers", response_model=TriggerHistoryOut)
def list_triggers(
    limit: int = Query(default=10, ge=1, le=500),
    cursor: str = Query(default=""),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    camera_id: str = Query(default=""),
    trigger_type: str = Query(default=""),
    category: str = Query(default=""),
    event_id: str = Query(default=""),
) -> TriggerHistoryOut:
    return history_svc.list_triggers(
        limit=limit,
        cursor=cursor,
        since=since,
        until=until,
        camera_id=camera_id,
        trigger_type=trigger_type,
        category=category,
        event_id=event_id,
    )


@router.get("/triggers/{event_id}", response_model=TriggerEventDetailOut)
def get_trigger(event_id: str) -> TriggerEventDetailOut:
    return history_svc.get_trigger(event_id)


@router.get("/triggers/{event_id}/clip", response_model=ClipUrlOut)
def get_trigger_clip(event_id: str) -> ClipUrlOut:
    return history_svc.get_trigger_clip(event_id)


@router.post("/triggers/{event_id}/resend", response_model=ResendOut)
def post_trigger_resend(event_id: str) -> ResendOut:
    return history_svc.resend_trigger(event_id)


@router.get("/sends", response_model=SendHistoryOut)
def list_sends(
    limit: int = Query(default=10, ge=1, le=500),
    cursor: str = Query(default=""),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    status: str = Query(default=""),
    event_id: str = Query(default=""),
    sink: str = Query(default=""),
) -> SendHistoryOut:
    return history_svc.list_sends(
        limit=limit,
        cursor=cursor,
        since=since,
        until=until,
        status=status,
        event_id=event_id,
        sink=sink,
    )


@router.get("/outbound", response_model=OutboundJobListOut)
def list_outbound(
    limit: int = Query(default=10, ge=1, le=500),
    cursor: str = Query(default=""),
    status: str = Query(default=""),
    event_id: str = Query(default=""),
) -> OutboundJobListOut:
    return history_svc.list_outbound(
        limit=limit,
        cursor=cursor,
        status=status,
        event_id=event_id,
    )


@router.post("/outbound/{job_id}/retry", response_model=OutboundJobOut)
def post_outbound_retry(job_id: str) -> OutboundJobOut:
    return history_svc.retry_outbound(job_id)
