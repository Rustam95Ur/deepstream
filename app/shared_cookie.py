"""Parent-domain session shared with every Nexus site."""

from __future__ import annotations

import os
from urllib.parse import quote

from fastapi import Request, Response

COOKIE = "nexus_session"
_MAX_AGE = 60 * 60 * 12


def _domain() -> str:
    return (os.environ.get("SESSION_COOKIE_DOMAIN") or "").strip()


def set_shared_cookie(response: Response, token: str) -> None:
    token = (token or "").strip()
    if not token:
        return
    kwargs: dict = {
        "max_age": _MAX_AGE,
        "httponly": True,
        "samesite": "lax",
        "path": "/",
    }
    domain = _domain()
    if domain:
        kwargs["domain"] = domain
        kwargs["secure"] = True
    response.set_cookie(COOKIE, token, **kwargs)


def clear_shared_cookie(response: Response) -> None:
    domain = _domain()
    if domain:
        response.delete_cookie(COOKIE, path="/", domain=domain, secure=True, samesite="lax")
        return
    response.delete_cookie(COOKIE, path="/")


def read_shared_cookie(request: Request) -> str:
    return (request.cookies.get(COOKIE) or "").strip()


def _panel() -> str:
    return (os.environ.get("PANEL_URL") or "").strip().rstrip("/")


def _sso() -> str:
    return (os.environ.get("NEXUS_SSO_URL") or "").strip().rstrip("/")


def enter_url(module: str) -> str:
    panel = _panel()
    sso = _sso()
    if not panel or not sso:
        return ""
    return f"{sso}/api/v1/auth/enter?module={quote(module)}&return={quote(panel + '/', safe='')}"


def logout_url() -> str:
    panel = _panel()
    sso = _sso()
    if not panel or not sso:
        return ""
    return f"{sso}/api/v1/auth/logout?return={quote(panel + '/login', safe='')}"
