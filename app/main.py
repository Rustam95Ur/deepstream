"""FastAPI entrypoint for Nexus DeepStream node (control plane only)."""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.auth import router as auth_router
from app.api.cameras import router as cameras_router
from app.api.errors import register_error_handlers
from app.api.history import router as history_router
from app.api.public_clips import router as public_clips_router
from app.api.node import router as node_router
from app.api.users import router as users_router
from app.api.webhooks import router as webhooks_router
from app.billing import apply_runtime_lock, validate_billing_key
from app.db import init_db
from app.history import get_history_writer
from app.logging_config import bind_context, configure_logging, log_extra
from app.minio_store import advertised_public_base
from app.storage import get_store
from app.web import SPA_DIR, router as web_router
from app.webhooks import get_outbound_worker, seed_webhooks_from_settings

configure_logging(service="nexus-deepstream", role="api")
logger = logging.getLogger("nexus_deepstream")

_billing_stop = threading.Event()
_billing_thread: threading.Thread | None = None
_BILLING_RECHECK_S = 300.0


def _billing_watch() -> None:
    while not _billing_stop.wait(_BILLING_RECHECK_S):
        try:
            check = apply_runtime_lock(validate_billing_key())
            logger.info(
                "billing recheck",
                extra=log_extra(
                    billing_valid=check.valid,
                    reason=check.reason or "-",
                ),
            )
        except Exception:
            logger.exception("billing recheck failed")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _billing_thread
    init_db()
    store = get_store()
    settings = store.get_settings()
    bind_context(node_id=settings.node_id)
    seed_webhooks_from_settings(settings)
    logger.info(
        "Nexus DeepStream API started",
        extra=log_extra(
            version=__version__,
            data_dir=str(store.data_dir),
            campus_clips=advertised_public_base(),
        ),
    )
    check = apply_runtime_lock(validate_billing_key(settings))
    logger.info(
        "billing check",
        extra=log_extra(
            billing_valid=check.valid,
            reason=check.reason or "-",
            billing_url=check.url,
            motherboard_serial=check.motherboard_serial or "-",
        ),
    )
    _billing_stop.clear()
    _billing_thread = threading.Thread(
        target=_billing_watch, name="billing-recheck", daemon=True
    )
    _billing_thread.start()
    # HistoryWriter + OutboundWorker also run on video. Dual outbound is
    # intentional (SKIP LOCKED). HistoryWriter on API covers record_send from
    # resend/enqueue without relying on the video process.
    get_history_writer().start()
    get_outbound_worker().start()
    yield
    _billing_stop.set()
    if _billing_thread and _billing_thread.is_alive():
        _billing_thread.join(timeout=3.0)
    get_outbound_worker().stop()
    get_history_writer().stop()


app = FastAPI(
    title="Nexus DeepStream",
    version=__version__,
    description="Standalone DeepStream first-line node (cameras + triggers)",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

spa_assets = SPA_DIR / "assets"
if spa_assets.is_dir():
    app.mount("/assets", StaticFiles(directory=str(spa_assets)), name="spa-assets")

app.include_router(public_clips_router)
app.include_router(auth_router)
app.include_router(node_router)
app.include_router(cameras_router)
app.include_router(webhooks_router)
app.include_router(users_router)
app.include_router(history_router)
app.include_router(web_router)
register_error_handlers(app)


def main() -> None:
    import uvicorn

    from app.settings import load_env_bootstrap

    boot = load_env_bootstrap()
    uvicorn.run(
        "app.main:app",
        host=boot.host,
        port=boot.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
