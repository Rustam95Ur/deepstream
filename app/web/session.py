"""Cookie session for the web UI (HMAC of the API token)."""

from __future__ import annotations

import hmac
import secrets

from fastapi import Request, Response

from app.storage import get_store

COOKIE_NAME = "nds_ui"
_HMAC_KEY = b"nexus-deepstream-ui-v1"
_MAX_AGE = 60 * 60 * 24 * 7


def _digest(token: str) -> str:
    return hmac.new(_HMAC_KEY, token.encode("utf-8"), "sha256").hexdigest()


def tokens_match(a: str, b: str) -> bool:
    if not a or not b or len(a) != len(b):
        return False
    return secrets.compare_digest(a, b)


def is_authed(request: Request) -> bool:
    token = (get_store().get_settings().api_token or "").strip()
    if not token:
        return False
    cookie = request.cookies.get(COOKIE_NAME) or ""
    return tokens_match(cookie, _digest(token))


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        _digest(token),
        max_age=_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")
