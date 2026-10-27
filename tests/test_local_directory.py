"""A local install keeps its own organizations and does not call billing."""

from app.services.organization_sync import sync_organizations


def test_local_install_does_not_call_the_billing_directory(monkeypatch):
    monkeypatch.delenv("NEXUS_SSO_URL", raising=False)

    def refuse(*_args, **_kwargs):
        raise AssertionError("directory must stay unused")

    monkeypatch.setattr("app.services.organization_sync._get_json", refuse)
    assert sync_organizations() == {"ok": True, "synced": 0, "deactivated": 0, "detail": ""}
