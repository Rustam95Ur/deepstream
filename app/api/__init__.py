"""API auth (Bearer token, UI cookie, or optional query)."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from app.storage import get_store
from app.users import UserRecord, has_users
from app.web.session import get_session_user


def require_api_token(request: Request) -> UserRecord | None:
    user = get_session_user(request)
    if user:
        request.state.user = user
        return user

    settings = get_store().get_settings()
    expected = (settings.api_token or "").strip()
    auth = (request.headers.get("Authorization") or "").strip()
    if expected and auth == f"Bearer {expected}":
        request.state.user = None
        return None
    if expected and request.query_params.get("token") == expected:
        request.state.user = None
        return None
    if not expected and not has_users():
        request.state.user = None
        return None
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API token",
        headers={"WWW-Authenticate": "Bearer"},
    )


ApiAuth = Depends(require_api_token)
