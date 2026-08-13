"""Settings + health + worker control API."""

from __future__ import annotations

from fastapi import APIRouter, Body

from app import __version__
from app.api import ApiAuth
from app.schemas import HealthOut, VideoHealthOut, WorkerStatusOut
from app.settings import NodeSettings
from app.storage import get_store
from app.video_client import notify_reload, video_health, worker_start, worker_status, worker_stop
from app.webhooks import list_enabled_webhooks

router = APIRouter(prefix="/api/v1", tags=["node"])


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    store = get_store()
    settings = store.get_settings()
    cams = store.list_cameras()
    st = worker_status()
    try:
        hooks = list_enabled_webhooks()
        triggers_url = hooks[0].url if hooks else settings.triggers_url
    except Exception:
        triggers_url = settings.triggers_url
    return HealthOut(
        status="ok",
        node_id=settings.node_id,
        node_name=settings.node_name,
        version=__version__,
        cameras_count=len(cams),
        cameras_enabled=sum(1 for c in cams if c.enabled),
        pipeline_running=st.running,
        pipeline_available=st.available,
        pipeline_detail=st.detail,
        triggers_url=triggers_url,
    )


@router.get("/settings", response_model=NodeSettings, dependencies=[ApiAuth])
def get_settings() -> NodeSettings:
    return get_store().get_settings()


@router.put("/settings", response_model=NodeSettings, dependencies=[ApiAuth])
def put_settings(body: NodeSettings) -> NodeSettings:
    updated = get_store().update_settings(body.model_dump())
    notify_reload()
    return updated


@router.patch("/settings", response_model=NodeSettings, dependencies=[ApiAuth])
def patch_settings(body: dict = Body(...)) -> NodeSettings:
    updated = get_store().update_settings(body)
    notify_reload()
    return updated


@router.get("/worker", response_model=WorkerStatusOut, dependencies=[ApiAuth])
def get_worker_status() -> WorkerStatusOut:
    return worker_status()


@router.get("/video/health", response_model=VideoHealthOut, dependencies=[ApiAuth])
def get_video_health() -> VideoHealthOut:
    return video_health()


@router.post("/worker/start", response_model=WorkerStatusOut, dependencies=[ApiAuth])
def post_worker_start() -> WorkerStatusOut:
    return worker_start()


@router.post("/worker/stop", response_model=WorkerStatusOut, dependencies=[ApiAuth])
def post_worker_stop() -> WorkerStatusOut:
    return worker_stop()


@router.post("/worker/reload", response_model=WorkerStatusOut, dependencies=[ApiAuth])
def post_worker_reload() -> WorkerStatusOut:
    return notify_reload() or worker_status()
