"""Video process: DeepStream pipeline + incident ring-buffer (rtsp_writer)."""

from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text

from app.db import db_enabled, get_engine, session_scope
from app.ds.log_buffer import install as install_log_buffer
from app.ds.log_buffer import snapshot as log_snapshot
from app.ds.ring_buffer import get_ring_buffer
from app.history import get_history_writer
from app.schemas import LogLineOut, RingCameraHealthOut, VideoHealthOut, WorkerStatusOut
from app.minio_store import advertised_public_base
from app.storage import get_store
from app.video_auth import require_video_token, video_token
from app.webhooks import get_outbound_worker
from app.worker import get_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("nexus_deepstream.video")

_watch_stop = threading.Event()
_watch_thread: threading.Thread | None = None
VideoAuth = Depends(require_video_token)


def _wait_for_db(*, attempts: int = 40, delay_s: float = 2.0) -> None:
    if not db_enabled():
        raise RuntimeError("NEXUS_DS_DATABASE_URL is required")
    last: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            get_engine()
            with session_scope(write=False) as session:
                session.execute(text("SELECT 1"))
            logger.info("video: database ready")
            return
        except Exception as exc:
            last = exc
            logger.warning("video: waiting for database (%s/%s): %s", i, attempts, exc)
            time.sleep(delay_s)
    raise RuntimeError(f"database not ready: {last}")


def _config_fingerprint() -> tuple[str, tuple]:
    store = get_store()
    store.invalidate_camera_cache()
    settings = store.get_settings()
    cams = tuple(
        (
            c.id,
            c.name,
            c.main_uri,
            c.enabled,
            tuple(c.enabled_triggers) if c.enabled_triggers is not None else None,
        )
        for c in store.list_cameras()
        if c.enabled
    )
    return settings.model_dump_json(), cams


def _watch_config() -> None:
    last: tuple[str, tuple] | None = None
    while not _watch_stop.wait(2.0):
        try:
            fp = _config_fingerprint()
        except Exception:
            logger.exception("video: config watch failed")
            continue
        if last is not None and fp != last:
            logger.info(
                "video: cameras/settings changed — reload pipeline + ring-buffer"
            )
            get_manager().request_reload()
            get_ring_buffer().request_refresh()
        last = fp


def _start_watch() -> None:
    global _watch_thread
    _watch_stop.clear()
    _watch_thread = threading.Thread(
        target=_watch_config, name="video-config-watch", daemon=True
    )
    _watch_thread.start()


def _stop_watch() -> None:
    _watch_stop.set()
    t = _watch_thread
    if t and t.is_alive():
        t.join(timeout=3.0)


def video_health() -> VideoHealthOut:
    store = get_store()
    settings = store.get_settings()
    ring = get_ring_buffer().status()
    cameras = [
        RingCameraHealthOut(
            camera_id=str(item.get("camera_id") or ""),
            name=str(item.get("name") or ""),
            alive=bool(item.get("alive")),
            stalled=bool(item.get("stalled")),
            last_segment_age_s=item.get("last_segment_age_s"),
            restarts=int(item.get("restarts") or 0),
            codec=str(item.get("codec") or ""),
            last_error=str(item.get("last_error") or ""),
        )
        for item in ring.get("cameras") or []
        if isinstance(item, dict)
    ]
    errors = [LogLineOut.model_validate(row) for row in log_snapshot(40)]
    seen = {e.message for e in errors}
    for cam in cameras:
        if cam.last_error and cam.last_error not in seen:
            errors.insert(
                0,
                LogLineOut(
                    level="ERROR",
                    logger=f"ring.{cam.name or cam.camera_id}",
                    message=cam.last_error,
                ),
            )
            seen.add(cam.last_error)
    pipe = get_manager().status()
    pipe.recent_errors = errors
    return VideoHealthOut(
        status="ok",
        gst_available=bool(ring.get("gst_available")),
        clip_record=bool(settings.enable_clip_record),
        ring_running=bool(ring.get("ring_running")),
        pipeline=pipe,
        cameras=cameras,
        recent_errors=errors,
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _wait_for_db()
    install_log_buffer()
    get_history_writer().start()
    get_outbound_worker().start()
    get_ring_buffer().start()
    settings = get_store().get_settings()
    logger.info(
        "Nexus DeepStream video node_id=%s auto_start=%s token=%s campus_clips=%s",
        settings.node_id,
        settings.auto_start_pipeline,
        "on" if video_token() else "off",
        advertised_public_base(),
    )
    if settings.auto_start_pipeline:
        get_manager().start()
    _start_watch()
    yield
    _stop_watch()
    get_manager().stop()
    get_ring_buffer().stop()
    get_outbound_worker().stop()
    get_history_writer().stop()


app = FastAPI(
    title="Nexus DeepStream Video",
    description="Internal control plane for GPU pipeline + RTSP ring-buffer",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/worker", response_model=WorkerStatusOut, dependencies=[VideoAuth])
def worker_status() -> WorkerStatusOut:
    return get_manager().status()


@app.post("/worker/start", response_model=WorkerStatusOut, dependencies=[VideoAuth])
def worker_start() -> WorkerStatusOut:
    get_ring_buffer().request_refresh()
    return get_manager().start()


@app.post("/worker/stop", response_model=WorkerStatusOut, dependencies=[VideoAuth])
def worker_stop() -> WorkerStatusOut:
    return get_manager().stop()


@app.post("/worker/reload", response_model=WorkerStatusOut, dependencies=[VideoAuth])
def worker_reload() -> WorkerStatusOut:
    store = get_store()
    store.invalidate_camera_cache()
    logger.info("video: reload requested")
    get_manager().request_reload()
    get_ring_buffer().request_refresh()
    return get_manager().status()


@app.get("/video/health", response_model=VideoHealthOut, dependencies=[VideoAuth])
def get_video_health() -> VideoHealthOut:
    return video_health()


def main() -> None:
    import uvicorn

    host = (os.environ.get("NEXUS_DS_VIDEO_HOST") or "0.0.0.0").strip()
    port = int(os.environ.get("NEXUS_DS_VIDEO_PORT") or "8081")
    uvicorn.run(
        "app.video:app",
        host=host,
        port=port,
        reload=False,
        workers=1,
        timeout_keep_alive=30,
        access_log=False,
    )


if __name__ == "__main__":
    main()
