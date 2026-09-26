"""Webhook domain dataclass."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.models import WebhookRow


@dataclass(frozen=True, slots=True)
class Webhook:
    id: str
    name: str
    url: str
    enabled: bool
    login: str
    auth_configured: bool
    timeout_sec: float
    max_retries: int
    created_at: datetime
    updated_at: datetime

    @property
    def max_attempts(self) -> int:
        return max(1, int(self.max_retries) + 1)


def from_row(row: WebhookRow) -> Webhook:
    return Webhook(
        id=row.id,
        name=row.name or "",
        url=(row.url or "").strip(),
        enabled=bool(row.enabled),
        login=(row.login or "").strip(),
        auth_configured=bool(
            (row.login or "").strip() and (row.password_hash or "").strip()
        ),
        timeout_sec=float(row.timeout_sec or 5.0),
        max_retries=int(row.max_retries or 0),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
