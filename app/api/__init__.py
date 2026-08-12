"""API auth (Bearer token, UI cookie, or optional query)."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from app.storage import get_store
from app.web.session import is_authed


def require_api_token(request: Request) -> None:
    settings = get_store().get_settings()
    expected = (settings.api_token or "").strip()
    if not expected:
        return
    auth = (request.headers.get("Authorization") or "").strip()
    if auth == f"Bearer {expected}":
        return
    if request.query_params.get("token") == expected:
        return
    if is_authed(request):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API token",
        headers={"WWW-Authenticate": "Bearer"},
    )


ApiAuth = Depends(require_api_token)
