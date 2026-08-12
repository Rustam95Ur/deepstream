"""JSON auth for the Vue SPA (httpOnly cookie session)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.schemas import LoginIn, SessionOut
from app.storage import get_store
from app.users import EmailTakenError, UserRecord, create_user, get_user_by_email, has_users
from app.web.passwords import verify_password
from app.web.session import (
    clear_session_cookie,
    get_session_user,
    secrets_match,
    set_session_cookie,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _session_out(*, user: UserRecord | None = None, authenticated: bool | None = None) -> SessionOut:
    settings = get_store().get_settings()
    authed = bool(user) if authenticated is None else authenticated
    return SessionOut(
        authenticated=authed,
        setup=not has_users(),
        user_id=user.id if user else "",
        email=user.email if user else "",
        name=user.name if user else "",
        node_id=settings.node_id,
        node_name=settings.node_name,
    )


@router.get("/session", response_model=SessionOut)
def auth_session(request: Request) -> SessionOut:
    return _session_out(user=get_session_user(request))


@router.post("/login", response_model=SessionOut)
def auth_login(body: LoginIn, response: Response) -> SessionOut:
    if not has_users():
        if len(body.password) < 8:
            raise HTTPException(status_code=400, detail="Минимум 8 символов")
        if not secrets_match(body.password, body.password_confirm or ""):
            raise HTTPException(status_code=400, detail="Пароли не совпадают")
        try:
            user = create_user(body.email, body.password)
        except EmailTakenError:
            raise HTTPException(status_code=409, detail="Email уже занят") from None
        set_session_cookie(response, user)
        return _session_out(user=user)

    user = get_user_by_email(body.email)
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
        )
    set_session_cookie(response, user)
    return _session_out(user=user)


@router.post("/logout", response_model=SessionOut)
def auth_logout(response: Response) -> SessionOut:
    clear_session_cookie(response)
    return _session_out(authenticated=False)
