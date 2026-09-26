"""Billing check model and license message constants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

LICENSE_LOCKED = "Лицензия недействительна. Pipeline и доступ к ноде отключены."

REASON_LABELS = {
    "missing_api_key": "ключ не задан",
    "not_checked": "ещё не проверялся",
    "key_not_found": "ключ не найден",
    "client_inactive": "клиент отключён",
    "subscription_expired": "подписка истекла",
    "stolen_key": "ключ привязан к другой плате",
    "invalid": "ключ отклонён",
}


@dataclass(slots=True)
class BillingCheck:
    url: str
    motherboard_serial: str
    api_key_configured: bool
    valid: bool
    reason: str = ""
    destroy: bool = False
    client_name: str = ""
    module: str = ""
    checked_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "motherboard_serial": self.motherboard_serial,
            "api_key_configured": self.api_key_configured,
            "valid": self.valid,
            "reason": self.reason,
            "destroy": self.destroy,
            "client_name": self.client_name,
            "module": self.module,
            "checked_at": self.checked_at,
        }
