"""FastAPI entrypoint for Nexus DeepStream node."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.auth import router as auth_router
from app.api.cameras import router as cameras_router
from app.api.node import router as node_router
from app.storage import get_store
from app.web import SPA_DIR, router as web_router
from app.worker import get_manager
from app.worker.cameras_poller import get_poller

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("nexus_deepstream")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    store = get_store()
    settings = store.get_settings()
    logger.info(
        "Nexus DeepStream v%s node_id=%s data=%s",
        __version__,
        settings.node_id,
        store.data_dir,
    )
    get_poller().start()
    if settings.auto_start_pipeline:
        get_manager().start()
    yield
    get_poller().stop()
    get_manager().stop()


app = FastAPI(
    title="Nexus DeepStream",
    version=__version__,
    description="Standalone DeepStream first-line node (cameras + triggers)",
    lifespan=lifespan,
)

static_dir = Path(__file__).resolve().parent / "web" / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

spa_assets = SPA_DIR / "assets"
if spa_assets.is_dir():
    app.mount("/assets", StaticFiles(directory=str(spa_assets)), name="spa-assets")

app.include_router(auth_router)
app.include_router(node_router)
app.include_router(cameras_router)
app.include_router(web_router)


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
