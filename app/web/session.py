"""Cookie session for the web UI (HMAC of user id + password hash)."""

from __future__ import annotations

import hmac
import secrets

from fastapi import Request, Response

from app.users import UserRecord, get_user

COOKIE_NAME = "nds_ui"
_HMAC_KEY = b"nexus-deepstream-ui-v2"
_MAX_AGE = 60 * 60 * 24 * 7


def _digest(user_id: str, password_hash: str) -> str:
    return hmac.new(
        _HMAC_KEY,
        f"{user_id}:{password_hash}".encode("utf-8"),
        "sha256",
    ).hexdigest()


def secrets_match(a: str, b: str) -> bool:
    if not a or not b or len(a) != len(b):
        return False
    return secrets.compare_digest(a, b)


def get_session_user(request: Request) -> UserRecord | None:
    cookie = request.cookies.get(COOKIE_NAME) or ""
    user_id, sep, digest = cookie.partition(".")
    if not sep or not user_id or not digest:
        return None
    user = get_user(user_id)
    if not user:
        return None
    if not secrets_match(digest, _digest(user.id, user.password_hash)):
        return None
    return user


def is_authed(request: Request) -> bool:
    return get_session_user(request) is not None


def set_session_cookie(response: Response, user: UserRecord) -> None:
    response.set_cookie(
        COOKIE_NAME,
        f"{user.id}.{_digest(user.id, user.password_hash)}",
        max_age=_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")
