"""SSO client: a token is accepted only for this module."""

from __future__ import annotations

import pytest

from app import sso


def _account(modules: list[str]) -> dict:
    return {
        "access_token": "tok",
        "account": {
            "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "email": "anna@school.local",
            "full_name": "Анна",
            "client_id": "client",
            "organization_id": "org",
            "modules": modules,
        },
    }


@pytest.fixture(autouse=True)
def _sso_url(monkeypatch):
    sso._cache.clear()
    monkeypatch.setenv("NEXUS_SSO_URL", "http://sso.test")


def test_login_rejects_another_module(monkeypatch):
    monkeypatch.setattr(sso, "_post_json", lambda path, body: (200, _account(["attendance"])))
    with pytest.raises(sso.SsoError) as exc:
        sso.login("anna@school.local", "secret")
    assert exc.value.status == 403


def test_login_returns_account_when_module_is_open(monkeypatch):
    monkeypatch.setattr(sso, "_post_json", lambda path, body: (200, _account([sso.MODULE])))
    account = sso.login("anna@school.local", "secret")
    assert account.organization_id == "org"
    assert sso.MODULE in account.modules


def test_introspect_ignores_token_without_this_module(monkeypatch):
    monkeypatch.setattr(
        sso,
        "_post_json",
        lambda path, body: (
            200,
            {
                "active": True,
                "account_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                "email": "anna@school.local",
                "full_name": "Анна",
                "client_id": "client",
                "organization_id": "org",
                "modules": ["attendance"],
            },
        ),
    )
    assert sso.introspect("tok") is None


def test_password_with_otp_returns_a_challenge_only_for_this_module(monkeypatch):
    def post(path, body):
        assert path == "/api/v1/auth/login"
        return (
            200,
            {
                "otp_required": True,
                "otp_setup": True,
                "challenge_token": "challenge",
                "access_token": "",
                "account": _account([sso.MODULE])["account"],
            },
        )

    monkeypatch.setattr(sso, "_post_json", post)
    challenge = sso.login("anna@school.local", "secret")
    assert isinstance(challenge, sso.SsoChallenge)
    assert challenge.token == "challenge"
    assert challenge.setup is True
    assert challenge.organization_id == "org"


def test_otp_challenge_rejects_another_module(monkeypatch):
    monkeypatch.setattr(
        sso,
        "_post_json",
        lambda path, body: (
            200,
            {
                "otp_required": True,
                "otp_setup": False,
                "challenge_token": "challenge",
                "account": _account(["attendance"])["account"],
            },
        ),
    )
    with pytest.raises(sso.SsoError) as exc:
        sso.login("anna@school.local", "secret")
    assert exc.value.status == 403


def test_wrong_password_is_unauthorized(monkeypatch):
    monkeypatch.setattr(sso, "_post_json", lambda path, body: (401, {"detail": "Неверный email или пароль"}))
    with pytest.raises(sso.SsoError) as exc:
        sso.login("anna@school.local", "nope")
    assert exc.value.status == 401
