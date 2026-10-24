"""Bind an SSO account to the organization copied from billing."""

from __future__ import annotations

from app.db import session_scope
from app.models import OrganizationRow
from app.sso import SsoAccount, introspect
from app.timeutil import utcnow
from app.users import UserRecord

ORG_UNAVAILABLE = "Организация этого сотрудника недоступна в модуле. Проверьте синхронизацию справочника."


def organization_ready(billing_id: str) -> bool:
    billing_id = (billing_id or "").strip()
    if not billing_id:
        return False
    with session_scope(write=False) as session:
        row = session.get(OrganizationRow, billing_id)
        return row is not None and bool(row.is_active)


def console_user(account: SsoAccount) -> UserRecord:
    now = utcnow()
    return UserRecord(
        id=account.account_id,
        email=account.email,
        name=account.full_name,
        password_hash="",
        created_at=now,
        updated_at=now,
    )


def user_from_token(token: str) -> UserRecord | None:
    account = introspect(token)
    if account is None or not organization_ready(account.organization_id):
        return None
    return console_user(account)
