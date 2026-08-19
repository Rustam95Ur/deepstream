"""FastAPI entrypoint for Nexus DeepStream node (control plane only)."""

from __future__ import annotations

import logging
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
from app.db import init_db
from app.storage import get_store
from app.web import SPA_DIR, router as web_router
from app.webhooks import get_outbound_worker, seed_webhooks_from_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("nexus_deepstream")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    store = get_store()
    settings = store.get_settings()
    seed_webhooks_from_settings(settings)
    logger.info(
        "Nexus DeepStream API v%s node_id=%s data=%s",
        __version__,
        settings.node_id,
        store.data_dir,
    )
    get_outbound_worker().start()
    yield
    get_outbound_worker().stop()


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
