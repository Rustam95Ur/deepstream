"""JSON auth for the Vue SPA (httpOnly cookie session)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.storage import get_store
from app.web.session import (
    clear_session_cookie,
    is_authed,
    set_session_cookie,
    tokens_match,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginIn(BaseModel):
    token: str = Field(..., min_length=1)
    token_confirm: str = ""


class SessionOut(BaseModel):
    authenticated: bool
    setup: bool
    node_id: str
    node_name: str


@router.get("/session", response_model=SessionOut)
def auth_session(request: Request) -> SessionOut:
    settings = get_store().get_settings()
    setup = not bool((settings.api_token or "").strip())
    return SessionOut(
        authenticated=is_authed(request),
        setup=setup,
        node_id=settings.node_id,
        node_name=settings.node_name,
    )


@router.post("/login", response_model=SessionOut)
def auth_login(body: LoginIn, response: Response) -> SessionOut:
    store = get_store()
    settings = store.get_settings()
    expected = (settings.api_token or "").strip()
    submitted = body.token.strip()

    if not expected:
        confirm = body.token_confirm.strip()
        if len(submitted) < 4:
            raise HTTPException(status_code=400, detail="Минимум 4 символа")
        if not tokens_match(submitted, confirm):
            raise HTTPException(status_code=400, detail="Токены не совпадают")
        settings = store.update_settings({"api_token": submitted})
        set_session_cookie(response, submitted)
        return SessionOut(
            authenticated=True,
            setup=False,
            node_id=settings.node_id,
            node_name=settings.node_name,
        )

    if not tokens_match(submitted, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный токен",
        )

    set_session_cookie(response, expected)
    return SessionOut(
        authenticated=True,
        setup=False,
        node_id=settings.node_id,
        node_name=settings.node_name,
    )


@router.post("/logout", response_model=SessionOut)
def auth_logout(response: Response) -> SessionOut:
    clear_session_cookie(response)
    settings = get_store().get_settings()
    return SessionOut(
        authenticated=False,
        setup=not bool((settings.api_token or "").strip()),
        node_id=settings.node_id,
        node_name=settings.node_name,
    )
