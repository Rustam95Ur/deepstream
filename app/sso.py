"""Ask Nexus SSO who this person is and whether this module is open."""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

MODULE = "redshift"
_TIMEOUT = 5.0
_CACHE_TTL = 10.0
_cache: dict[str, tuple[float, SsoAccount]] = {}
_lock = threading.Lock()


class SsoError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class SsoAccount:
    token: str
    account_id: str
    email: str
    full_name: str
    client_id: str
    organization_id: str
    modules: tuple[str, ...]


@dataclass(frozen=True)
class SsoChallenge:
    token: str
    setup: bool
    organization_id: str


def configured() -> bool:
    return bool(_base_url())


def _base_url() -> str:
    return (os.environ.get("NEXUS_SSO_URL") or "").strip().rstrip("/")


def login(email: str, password: str) -> SsoAccount | SsoChallenge:
    if not configured():
        raise SsoError(503, "SSO не настроен")
    status, payload = _post_json(
        "/api/v1/auth/login",
        {"email": email.strip().lower(), "password": password},
    )
    if status in {400, 401, 422}:
        raise SsoError(401, "Неверный email или пароль")
    if status != 200:
        raise SsoError(503, "SSO недоступен")
    if payload.get("otp_required"):
        return _challenge(payload)
    account = _from_login(payload)
    if MODULE not in account.modules:
        raise SsoError(403, "Этот модуль вам не открыт")
    return account


def fetch_otp_setup(challenge: str) -> dict:
    status, payload = _post_json("/api/v1/auth/otp/setup", {"challenge_token": challenge})
    if status != 200:
        raise SsoError(status if status < 500 else 503, str(payload.get("detail") or "Не удалось показать QR-код"))
    return payload


def submit_otp(challenge: str, code: str) -> SsoAccount:
    status, payload = _post_json(
        "/api/v1/auth/otp/confirm",
        {"challenge_token": challenge, "code": code},
    )
    if status == 400:
        raise SsoError(400, str(payload.get("detail") or "Неверный код. Попробуйте ещё раз."))
    if status != 200:
        raise SsoError(401 if status == 401 else 503, str(payload.get("detail") or "Сначала войдите по паролю"))
    account = _from_login(payload)
    if MODULE not in account.modules:
        raise SsoError(403, "Этот модуль вам не открыт")
    return account


def _challenge(payload: dict) -> SsoChallenge:
    account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
    modules = account.get("modules") or []
    if not isinstance(modules, list) or MODULE not in {str(item) for item in modules}:
        raise SsoError(403, "Этот модуль вам не открыт")
    token = str(payload.get("challenge_token") or "")
    if not token:
        raise SsoError(503, "SSO вернул пустой ответ")
    return SsoChallenge(
        token=token,
        setup=bool(payload.get("otp_setup")),
        organization_id=str(account.get("organization_id") or ""),
    )


def introspect(token: str) -> SsoAccount | None:
    token = (token or "").strip()
    if not token or not configured():
        return None
    now = time.monotonic()
    with _lock:
        hit = _cache.get(token)
        if hit and hit[0] > now:
            return hit[1]
    status, payload = _post_json("/api/v1/auth/introspect", {"token": token})
    if status != 200 or not payload.get("active"):
        return None
    account = _from_introspect(token, payload)
    if account is None or MODULE not in account.modules:
        return None
    with _lock:
        _cache[token] = (time.monotonic() + _CACHE_TTL, account)
        if len(_cache) > 256:
            _cache.clear()
            _cache[token] = (time.monotonic() + _CACHE_TTL, account)
    return account


def redeem(code: str) -> SsoAccount | None:
    status, payload = _post_json("/api/v1/auth/handover", {"code": code})
    if status != 200 or not payload.get("active"):
        return None
    token = str(payload.get("access_token") or "")
    account = _from_introspect(token, payload)
    if account is None or MODULE not in account.modules:
        return None
    return account


def _from_login(payload: dict) -> SsoAccount:
    account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
    token = str(payload.get("access_token") or "")
    built = _account(token, account)
    if built is None:
        raise SsoError(503, "SSO вернул пустой ответ")
    return built


def _from_introspect(token: str, payload: dict) -> SsoAccount | None:
    return _account(
        token,
        {
            "id": payload.get("account_id"),
            "email": payload.get("email"),
            "full_name": payload.get("full_name"),
            "client_id": payload.get("client_id"),
            "organization_id": payload.get("organization_id"),
            "modules": payload.get("modules"),
        },
    )


def _account(token: str, account: dict) -> SsoAccount | None:
    account_id = str(account.get("id") or "")
    if not token or not account_id:
        return None
    modules = account.get("modules") or []
    if not isinstance(modules, list):
        modules = []
    return SsoAccount(
        token=token,
        account_id=account_id,
        email=str(account.get("email") or ""),
        full_name=str(account.get("full_name") or ""),
        client_id=str(account.get("client_id") or ""),
        organization_id=str(account.get("organization_id") or ""),
        modules=tuple(str(item) for item in modules),
    )


def _post_json(path: str, body: dict) -> tuple[int, dict]:
    if not configured():
        return 503, {}
    request = urllib.request.Request(
        _base_url() + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            payload = json.loads(response.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        return exc.code, payload
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return 503, {}
    if not isinstance(payload, dict):
        return 503, {}
    return 200, payload
