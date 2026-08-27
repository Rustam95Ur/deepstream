"""API auth: console session, webhook Basic for cameras, or first-boot open."""

from __future__ import annotations

import base64

from fastapi import Depends, HTTPException, Request, status

from app.users import UserRecord, has_users
from app.web.session import get_session_user
from app.webhooks import Webhook, authenticate_webhook_login

_CAM_WWW = 'Basic realm="nexus-cameras"'


def _unauthorized(detail: str, *, basic: bool = False) -> None:
    headers = {"WWW-Authenticate": _CAM_WWW if basic else "Bearer"}
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers=headers,
    )


def _parse_basic(auth: str) -> tuple[str, str] | None:
    if not auth.lower().startswith("basic "):
        return None
    try:
        raw = base64.b64decode(auth.split(" ", 1)[1].strip(), validate=True).decode(
            "utf-8"
        )
    except (ValueError, UnicodeDecodeError):
        return None
    login, sep, password = raw.partition(":")
    if not sep:
        return None
    return login, password


def _webhook_from_request(request: Request) -> Webhook | None:
    auth = (request.headers.get("Authorization") or "").strip()
    basic = _parse_basic(auth)
    if basic:
        return authenticate_webhook_login(basic[0], basic[1])
    login = (request.headers.get("X-Nexus-Login") or "").strip()
    password = request.headers.get("X-Nexus-Password") or ""
    if login:
        return authenticate_webhook_login(login, password)
    return None


def require_api_token(request: Request) -> UserRecord | None:
    user = get_session_user(request)
    if user:
        request.state.user = user
        return user
    if not has_users():
        request.state.user = None
        return None
    _unauthorized("Нужен вход в консоль")


def require_camera_auth(request: Request) -> UserRecord | Webhook | None:
    """Console session or webhook login/password (HTTP Basic)."""
    user = get_session_user(request)
    if user:
        request.state.user = user
        return user

    has_basic = bool(
        _parse_basic((request.headers.get("Authorization") or "").strip())
        or (request.headers.get("X-Nexus-Login") or "").strip()
    )
    if has_basic:
        hook = _webhook_from_request(request)
        if hook is None:
            _unauthorized("Invalid webhook login or password", basic=True)
        request.state.user = None
        request.state.webhook = hook
        return hook

    if not has_users():
        request.state.user = None
        return None
    _unauthorized("Invalid webhook login or password", basic=True)


ApiAuth = Depends(require_api_token)
CameraApiAuth = Depends(require_camera_auth)
