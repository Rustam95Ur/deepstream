"""API auth (optional Bearer token)."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from app.storage import get_store


def require_api_token(request: Request) -> None:
    settings = get_store().get_settings()
    expected = (settings.api_token or "").strip()
    if not expected:
        return
    auth = (request.headers.get("Authorization") or "").strip()
    if auth == f"Bearer {expected}":
        return
    # Also allow token query for simple UI forms (same origin only)
    if request.query_params.get("token") == expected:
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API token",
        headers={"WWW-Authenticate": "Bearer"},
    )


ApiAuth = Depends(require_api_token)
