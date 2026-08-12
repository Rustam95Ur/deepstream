"""Serve the Vue SPA from frontend/dist (local uvicorn). Docker uses nginx."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

SPA_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"
INDEX = SPA_DIR / "index.html"

router = APIRouter(tags=["web"])

_MISSING = HTMLResponse(
    "<p>UI not built. In <code>frontend/</code> run "
    "<code>npm install &amp;&amp; npm run build</code>.</p>",
    status_code=503,
)


def spa_index() -> FileResponse | HTMLResponse:
    if INDEX.is_file():
        return FileResponse(INDEX)
    return _MISSING


@router.get("/", response_model=None)
def spa_root():
    return spa_index()


@router.get("/login", response_model=None)
def spa_login():
    return spa_index()


@router.get("/{full_path:path}", response_model=None)
def spa_fallback(full_path: str):
    if full_path.startswith(("api/", "docs", "redoc", "openapi.json", "static/")):
        raise HTTPException(status_code=404, detail="Not found")
    target = (SPA_DIR / full_path).resolve()
    root = SPA_DIR.resolve()
    if target.is_file() and (target == root or root in target.parents):
        return FileResponse(target)
    return spa_index()
