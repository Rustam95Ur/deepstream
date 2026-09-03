"""Settings + health + worker control API."""

from __future__ import annotations

from fastapi import APIRouter, Body

from app import __version__
from app.api import ApiAuth, LicenseAuth
from app.billing import (
    apply_runtime_lock,
    billing_status,
    license_ok,
    license_reason,
    settings_for_check,
    validate_billing_key,
)
from app.pipeline_status import attach_status
from app.schemas import BillingCheckOut, BillingValidateIn, HealthOut, VideoHealthOut, WorkerStatusOut
from app.settings import NodeSettings
from app.storage import get_store
from app.video_client import (
    notify_reload,
    video_health,
    worker_start,
    worker_status,
    worker_stop,
)
from app.webhooks import list_enabled_webhooks

router = APIRouter(prefix="/api/v1", tags=["node"])


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    store = get_store()
    settings = store.get_settings()
    cams = store.list_cameras()
    st = worker_status()
    valid = license_ok()
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
        license_valid=valid,
        license_reason="" if valid else license_reason(),
    )


@router.get("/billing", response_model=BillingCheckOut, dependencies=[ApiAuth])
def get_billing() -> BillingCheckOut:
    return BillingCheckOut.model_validate(billing_status().as_dict())


@router.post("/billing/validate", response_model=BillingCheckOut, dependencies=[ApiAuth])
def post_billing_validate(
    body: BillingValidateIn = Body(default_factory=BillingValidateIn),
) -> BillingCheckOut:
    settings = settings_for_check(
        billing_url=body.billing_url,
        billing_api_key=body.billing_api_key,
    )
    check = apply_runtime_lock(validate_billing_key(settings))
    return BillingCheckOut.model_validate(check.as_dict())


@router.get("/settings", response_model=NodeSettings, dependencies=[ApiAuth])
def get_settings() -> NodeSettings:
    return get_store().get_settings()


def _billing_fields_changed(before: NodeSettings, after: NodeSettings) -> bool:
    return (
        before.billing_url != after.billing_url
        or before.billing_api_key != after.billing_api_key
        or before.billing_timeout_sec != after.billing_timeout_sec
    )


@router.put("/settings", response_model=NodeSettings, dependencies=[ApiAuth])
def put_settings(body: NodeSettings) -> NodeSettings:
    store = get_store()
    before = store.get_settings()
    updated = store.update_settings(body.model_dump())
    if _billing_fields_changed(before, updated):
        apply_runtime_lock(validate_billing_key(updated))
    notify_reload()
    return updated


@router.patch("/settings", response_model=NodeSettings, dependencies=[ApiAuth])
def patch_settings(body: dict = Body(...)) -> NodeSettings:
    store = get_store()
    before = store.get_settings()
    updated = store.update_settings(body)
    if _billing_fields_changed(before, updated):
        apply_runtime_lock(validate_billing_key(updated))
    notify_reload()
    return updated


def _with_skips(status: WorkerStatusOut) -> WorkerStatusOut:
    store = get_store()
    return attach_status(status, store.list_cameras(), store.get_settings())


@router.get("/worker", response_model=WorkerStatusOut, dependencies=[ApiAuth, LicenseAuth])
def get_worker_status() -> WorkerStatusOut:
    return _with_skips(worker_status())


@router.get("/video/health", response_model=VideoHealthOut, dependencies=[ApiAuth, LicenseAuth])
def get_video_health() -> VideoHealthOut:
    health = video_health()
    health.pipeline = _with_skips(health.pipeline)
    if not health.recent_errors:
        health.recent_errors = list(health.pipeline.recent_errors)
    return health


@router.post("/worker/start", response_model=WorkerStatusOut, dependencies=[ApiAuth, LicenseAuth])
def post_worker_start() -> WorkerStatusOut:
    return _with_skips(worker_start())


@router.post("/worker/stop", response_model=WorkerStatusOut, dependencies=[ApiAuth])
def post_worker_stop() -> WorkerStatusOut:
    return _with_skips(worker_stop())


@router.post("/worker/reload", response_model=WorkerStatusOut, dependencies=[ApiAuth, LicenseAuth])
def post_worker_reload() -> WorkerStatusOut:
    return _with_skips(notify_reload() or worker_status())
