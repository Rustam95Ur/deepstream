"""Bearer token for the internal video control plane (:8081)."""

from __future__ import annotations

import os

from fastapi import HTTPException, Request, status


def video_token() -> str:
    return (os.environ.get("NEXUS_DS_VIDEO_TOKEN") or "").strip()


def require_video_token(request: Request) -> None:
    expected = video_token()
    if not expected:
        return
    auth = (request.headers.get("Authorization") or "").strip()
    if auth == f"Bearer {expected}":
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing video token",
        headers={"WWW-Authenticate": "Bearer"},
    )
