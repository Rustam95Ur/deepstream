"""Users in Postgres for console login."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db import session_scope
from app.models import UserRow
from app.web.passwords import hash_password


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


@dataclass(frozen=True)
class UserRecord:
    id: str
    email: str
    name: str
    password_hash: str
    created_at: datetime
    updated_at: datetime


def _record(row: UserRow) -> UserRecord:
    return UserRecord(
        id=row.id,
        email=row.email,
        name=row.name or "",
        password_hash=row.password_hash,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class EmailTakenError(Exception):
    pass


def user_count() -> int:
    with session_scope(write=False) as session:
        return int(session.scalar(select(func.count()).select_from(UserRow)) or 0)


def has_users() -> bool:
    return user_count() > 0


def get_user(user_id: str) -> UserRecord | None:
    with session_scope(write=False) as session:
        row = session.get(UserRow, user_id)
        return _record(row) if row else None


def get_user_by_email(email: str) -> UserRecord | None:
    email = normalize_email(email)
    if not email:
        return None
    with session_scope(write=False) as session:
        row = session.scalar(select(UserRow).where(UserRow.email == email))
        return _record(row) if row else None


def list_users() -> list[UserRecord]:
    with session_scope(write=False) as session:
        rows = session.scalars(select(UserRow).order_by(UserRow.email)).all()
        return [_record(r) for r in rows]


def create_user(email: str, password: str, name: str = "") -> UserRecord:
    email = normalize_email(email)
    now = _utcnow()
    row = UserRow(
        id=str(uuid4()),
        email=email,
        password_hash=hash_password(password),
        name=(name or "").strip(),
        created_at=now,
        updated_at=now,
    )
    try:
        with session_scope(write=True) as session:
            session.add(row)
            session.flush()
            return _record(row)
    except IntegrityError as exc:
        raise EmailTakenError(email) from exc


def delete_user(user_id: str) -> bool:
    with session_scope(write=True) as session:
        row = session.get(UserRow, user_id)
        if row is None:
            return False
        session.delete(row)
        return True


def update_user(user_id: str, *, email: str, name: str, password: str = "") -> UserRecord | None:
    email = normalize_email(email)
    now = _utcnow()
    try:
        with session_scope(write=True) as session:
            row = session.get(UserRow, user_id)
            if row is None:
                return None
            row.email = email
            row.name = (name or "").strip()
            if password:
                row.password_hash = hash_password(password)
            row.updated_at = now
            session.flush()
            return _record(row)
    except IntegrityError as exc:
        raise EmailTakenError(email) from exc
