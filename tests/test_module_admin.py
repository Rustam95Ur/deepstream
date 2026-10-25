"""A module admin has no billing organization and still enters the console."""

from app.sso import SsoAccount
from app.sso_user import organization_open, user_from_token


def test_empty_organization_is_open_without_the_directory(monkeypatch):
    monkeypatch.setattr(
        "app.sso_user.organization_ready",
        lambda billing_id: (_ for _ in ()).throw(AssertionError("directory must stay unused")),
    )
    assert organization_open("") is True


def test_employee_without_a_synced_organization_stays_out(monkeypatch):
    monkeypatch.setattr("app.sso_user.organization_ready", lambda billing_id: False)
    assert organization_open("missing") is False


def test_module_admin_token_is_accepted(monkeypatch):
    account = SsoAccount(
        token="tok",
        account_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        email="mod@nexus.local",
        full_name="Админ",
        client_id="",
        organization_id="",
        modules=("redshift",),
    )
    monkeypatch.setattr("app.sso_user.introspect", lambda token: account)
    monkeypatch.setattr(
        "app.sso_user.organization_ready",
        lambda billing_id: (_ for _ in ()).throw(AssertionError("directory must stay unused")),
    )
    user = user_from_token("tok")
    assert user is not None
    assert user.email == "mod@nexus.local"
