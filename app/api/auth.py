"""JSON auth for the Vue SPA (httpOnly cookie session)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.billing import license_lock_detail, license_ok
from pydantic import BaseModel, Field

from app.schemas import LoginIn, SessionOut
from app.storage import get_store
from app.sso import SsoChallenge, SsoError, configured as sso_configured
from app.sso import fetch_otp_setup, login as sso_login, submit_otp
from app.sso_user import ORG_UNAVAILABLE, console_user, organization_ready
from app.users import (
    EmailTakenError,
    UserRecord,
    create_user,
    get_user_by_email,
    has_users,
)
from app.web.passwords import verify_password
from app.web.session import (
    clear_session_cookie,
    get_session_user,
    secrets_match,
    read_sso_otp,
    set_session_cookie,
    set_sso_cookie,
    set_sso_otp_cookie,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class OtpTokenIn(BaseModel):
    token: str = Field(default="", max_length=16)


class OtpSetupOut(BaseModel):
    manual_key: str
    qr_data_uri: str
    issuer: str


def _session_out(
    *,
    user: UserRecord | None = None,
    authenticated: bool | None = None,
    otp_pending: bool = False,
    otp_setup: bool = False,
) -> SessionOut:
    settings = get_store().get_settings()
    authed = bool(user) if authenticated is None else authenticated
    valid = license_ok()
    return SessionOut(
        authenticated=authed,
        setup=not has_users() and not sso_configured(),
        user_id=user.id if user else "",
        email=user.email if user else "",
        name=user.name if user else "",
        node_id=settings.node_id,
        node_name=settings.node_name,
        license_valid=valid,
        license_reason="" if valid else license_lock_detail(),
        otp_pending=otp_pending,
        otp_setup=otp_setup,
    )


@router.get("/session", response_model=SessionOut)
def auth_session(request: Request) -> SessionOut:
    pending = read_sso_otp(request)
    if pending:
        return _session_out(authenticated=False, otp_pending=True, otp_setup=pending[1])
    return _session_out(user=get_session_user(request))


def _login_local(body: LoginIn, response: Response) -> SessionOut:
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


def _login_node_operator(body: LoginIn, response: Response, exc: SsoError) -> SessionOut:
    user = get_user_by_email(body.email)
    if user and verify_password(body.password, user.password_hash):
        set_session_cookie(response, user)
        return _session_out(user=user)
    raise HTTPException(status_code=exc.status, detail=exc.detail)


@router.post("/login", response_model=SessionOut)
def auth_login(body: LoginIn, response: Response) -> SessionOut:
    if not sso_configured():
        return _login_local(body, response)
    try:
        account = sso_login(body.email, body.password)
    except SsoError as exc:
        if exc.status == 403:
            raise HTTPException(status_code=exc.status, detail=exc.detail) from None
        return _login_node_operator(body, response, exc)
    if isinstance(account, SsoChallenge):
        if not organization_ready(account.organization_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ORG_UNAVAILABLE)
        set_sso_otp_cookie(response, account.token, setup=account.setup)
        return _session_out(authenticated=False, otp_pending=True, otp_setup=account.setup)
    if not organization_ready(account.organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ORG_UNAVAILABLE)
    set_sso_cookie(response, account.token)
    return _session_out(user=console_user(account))


def _finish_sso_otp(request: Request, response: Response, code: str) -> SessionOut | None:
    pending = read_sso_otp(request)
    if pending is None:
        return None
    try:
        account = submit_otp(pending[0], code)
    except SsoError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from None
    if not organization_ready(account.organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ORG_UNAVAILABLE)
    set_sso_cookie(response, account.token)
    return _session_out(user=console_user(account))


@router.get("/otp/setup", response_model=OtpSetupOut)
def otp_setup(request: Request) -> OtpSetupOut:
    pending = read_sso_otp(request)
    if pending is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Сначала войдите по паролю")
    try:
        data = fetch_otp_setup(pending[0])
    except SsoError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail) from None
    return OtpSetupOut(
        manual_key=str(data.get("manual_key") or ""),
        qr_data_uri=str(data.get("qr_data_uri") or ""),
        issuer=str(data.get("issuer") or "Nexus"),
    )


@router.post("/otp/confirm", response_model=SessionOut)
def otp_confirm(body: OtpTokenIn, request: Request, response: Response) -> SessionOut:
    finished = _finish_sso_otp(request, response, body.token)
    if finished is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Сначала войдите по паролю")
    return finished


@router.post("/otp/verify", response_model=SessionOut)
def otp_verify(body: OtpTokenIn, request: Request, response: Response) -> SessionOut:
    return otp_confirm(body, request, response)


@router.post("/logout", response_model=SessionOut)
def auth_logout(response: Response) -> SessionOut:
    clear_session_cookie(response)
    return _session_out(authenticated=False)
