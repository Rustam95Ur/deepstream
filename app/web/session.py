"""Cookie session for the web UI (HMAC of user id + password hash)."""

from __future__ import annotations

import hmac
import secrets

from fastapi import Request, Response

from app.sso_user import user_from_token
from app.users import UserRecord, get_user

COOKIE_NAME = "nds_ui"
SSO_PREFIX = "sso."
OTP_SETUP_PREFIX = "sso-otp.1."
OTP_CODE_PREFIX = "sso-otp.0."
_HMAC_KEY = b"nexus-deepstream-ui-v2"
_MAX_AGE = 60 * 60 * 24 * 7
_SSO_MAX_AGE = 60 * 60 * 12
_OTP_MAX_AGE = 60 * 5


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


def read_sso_otp(request: Request) -> tuple[str, bool] | None:
    cookie = request.cookies.get(COOKIE_NAME) or ""
    if cookie.startswith(OTP_SETUP_PREFIX):
        token = cookie[len(OTP_SETUP_PREFIX) :]
        return (token, True) if token else None
    if cookie.startswith(OTP_CODE_PREFIX):
        token = cookie[len(OTP_CODE_PREFIX) :]
        return (token, False) if token else None
    return None


def get_session_user(request: Request) -> UserRecord | None:
    cookie = request.cookies.get(COOKIE_NAME) or ""
    if cookie.startswith(OTP_SETUP_PREFIX) or cookie.startswith(OTP_CODE_PREFIX):
        return None
    if cookie.startswith(SSO_PREFIX):
        return user_from_token(cookie[len(SSO_PREFIX) :])
    from app.shared_cookie import read_shared_cookie

    shared = read_shared_cookie(request)
    if shared:
        user = user_from_token(shared)
        if user is not None:
            return user
    from app.sso import configured as sso_configured

    if sso_configured():
        return None
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


def set_sso_otp_cookie(response: Response, token: str, *, setup: bool) -> None:
    prefix = OTP_SETUP_PREFIX if setup else OTP_CODE_PREFIX
    response.set_cookie(
        COOKIE_NAME,
        f"{prefix}{token}",
        max_age=_OTP_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )


def set_sso_cookie(response: Response, token: str) -> None:
    from app.shared_cookie import set_shared_cookie

    response.set_cookie(
        COOKIE_NAME,
        f"{SSO_PREFIX}{token}",
        max_age=_SSO_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )
    set_shared_cookie(response, token)


def clear_session_cookie(response: Response) -> None:
    from app.shared_cookie import clear_shared_cookie

    response.delete_cookie(COOKIE_NAME, path="/")
    clear_shared_cookie(response)
