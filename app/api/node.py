"""Settings + health + worker control API."""

from __future__ import annotations

from fastapi import APIRouter, Body

from app import __version__
from app.api import ApiAuth
from app.schemas import HealthOut, WorkerStatusOut
from app.settings import NodeSettings
from app.storage import get_store
from app.worker import get_manager, pipeline_available
from app.worker.cameras_poller import get_poller

router = APIRouter(prefix="/api/v1", tags=["node"])


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    store = get_store()
    settings = store.get_settings()
    cams = store.list_cameras()
    st = get_manager().status()
    ok, detail = pipeline_available()
    return HealthOut(
        status="ok",
        node_id=settings.node_id,
        node_name=settings.node_name,
        version=__version__,
        cameras_count=len(cams),
        cameras_enabled=sum(1 for c in cams if c.enabled),
        pipeline_running=st.running,
        pipeline_available=ok,
        pipeline_detail=detail,
        triggers_url=settings.triggers_url,
        cameras_url=settings.cameras_url,
    )


@router.get("/settings", response_model=NodeSettings, dependencies=[ApiAuth])
def get_settings() -> NodeSettings:
    return get_store().get_settings()


@router.put("/settings", response_model=NodeSettings, dependencies=[ApiAuth])
def put_settings(body: NodeSettings) -> NodeSettings:
    updated = get_store().update_settings(body.model_dump())
    get_manager().request_reload()
    return updated


@router.patch("/settings", response_model=NodeSettings, dependencies=[ApiAuth])
def patch_settings(body: dict = Body(...)) -> NodeSettings:
    updated = get_store().update_settings(body)
    get_manager().request_reload()
    return updated


@router.get("/worker", response_model=WorkerStatusOut, dependencies=[ApiAuth])
def worker_status() -> WorkerStatusOut:
    return get_manager().status()


@router.post("/worker/start", response_model=WorkerStatusOut, dependencies=[ApiAuth])
def worker_start() -> WorkerStatusOut:
    return get_manager().start()


@router.post("/worker/stop", response_model=WorkerStatusOut, dependencies=[ApiAuth])
def worker_stop() -> WorkerStatusOut:
    return get_manager().stop()


@router.post("/worker/reload", response_model=WorkerStatusOut, dependencies=[ApiAuth])
def worker_reload() -> WorkerStatusOut:
    get_manager().request_reload()
    return get_manager().status()


@router.post("/cameras-pull", dependencies=[ApiAuth])
def cameras_pull() -> dict:
    n = get_poller().sync_once()
    return {"ok": True, "count": n}
