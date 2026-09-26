"""Bearer token for the internal video control plane (:8081)."""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.runtime_env import get_runtime_env


def video_token() -> str:
    return get_runtime_env().video_token


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
