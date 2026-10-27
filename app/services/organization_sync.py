"""Pull the organization directory from Nexus Billing."""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID

from sqlalchemy import select

from app.billing.validate import (
    BILLING_MODULE,
    billing_api_key,
    billing_url,
    is_admin_license_key,
    motherboard_serial,
)
from app.db import session_scope
from app.models import OrganizationRow
from app.storage import get_store
from app.timeutil import utcnow

logger = logging.getLogger(__name__)


def organizations_url(validate_url: str) -> str:
    url = (validate_url or "").strip().rstrip("/")
    marker = "/keys/validate"
    if url.endswith(marker):
        return f"{url[: -len(marker)]}/organizations"
    if url.endswith("/api/v1"):
        return f"{url}/public/organizations"
    return f"{url}/organizations"


def sync_organizations() -> dict[str, Any]:
    from app.sso import configured as sso_configured

    if not sso_configured():
        return {"ok": True, "synced": 0, "deactivated": 0, "detail": ""}
    try:
        return _sync()
    except Exception:
        logger.exception("organization sync failed")
        return {"ok": False, "synced": 0, "deactivated": 0, "detail": "sync failed"}


def _sync() -> dict[str, Any]:
    settings = get_store().get_settings()
    api_key = billing_api_key(settings)
    if not api_key:
        return {"ok": False, "synced": 0, "deactivated": 0, "detail": "Не задан ключ биллинга"}
    if is_admin_license_key(api_key):
        return {
            "ok": False,
            "synced": 0,
            "deactivated": 0,
            "detail": "Ключ администратора не ходит в биллинг за организациями",
        }

    status, payload, error = _get_json(
        organizations_url(billing_url(settings)),
        api_key=api_key,
        serial=motherboard_serial(),
        timeout_sec=float(settings.billing_timeout_sec or 5.0),
    )
    if status in {401, 403}:
        _synced, deactivated = _apply([], deactivate_all=True)
        logger.info("organization sync deactivated locals reason=%s", error or status)
        return {"ok": True, "synced": 0, "deactivated": deactivated, "detail": error or f"HTTP {status}"}
    if status != 200 or not isinstance(payload, dict) or not isinstance(payload.get("organizations"), list):
        logger.warning("organization sync skipped status=%s error=%s", status, error)
        return {"ok": False, "synced": 0, "deactivated": 0, "detail": error or "billing unreachable"}

    synced, deactivated = _apply(payload["organizations"], deactivate_all=False)
    logger.info("organization sync synced=%s deactivated=%s", synced, deactivated)
    return {"ok": True, "synced": synced, "deactivated": deactivated, "detail": ""}


def _apply(items: list[dict[str, Any]], *, deactivate_all: bool) -> tuple[int, int]:
    now = utcnow()
    with session_scope(write=True) as session:
        rows = session.scalars(select(OrganizationRow)).all()
        by_id = {row.id: row for row in rows}
        seen: set[str] = set()
        synced = 0
        if not deactivate_all:
            for item in items:
                billing_id = _billing_id(item.get("id"))
                name = str(item.get("name") or "").strip()
                if not billing_id or not name:
                    continue
                seen.add(billing_id)
                description = str(item.get("description") or "")
                active = bool(item.get("is_active", True))
                row = by_id.get(billing_id)
                if row is None:
                    session.add(
                        OrganizationRow(
                            id=billing_id,
                            name=name[:255],
                            description=description,
                            is_active=active,
                            updated_at=now,
                        )
                    )
                else:
                    row.name = name[:255]
                    row.description = description
                    row.is_active = active
                    row.updated_at = now
                synced += 1
        deactivated = 0
        for billing_id, row in by_id.items():
            if deactivate_all or billing_id not in seen:
                if row.is_active:
                    row.is_active = False
                    row.updated_at = now
                    deactivated += 1
        return synced, deactivated


def _billing_id(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return str(UUID(text))
    except ValueError:
        return ""


def _get_json(
    url: str,
    *,
    api_key: str,
    serial: str,
    timeout_sec: float,
) -> tuple[int | None, dict[str, Any] | None, str]:
    headers = {"Accept": "application/json", "X-API-Key": api_key, "X-Module": BILLING_MODULE}
    if serial:
        headers["X-Motherboard-Serial"] = serial
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=timeout_sec) as response:
            raw = response.read()
            status = int(response.status)
    except HTTPError as exc:
        return int(exc.code), None, _error_detail(exc.read()) or f"HTTP {exc.code}"
    except (URLError, TimeoutError, OSError) as exc:
        return None, None, str(exc)
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        return status, None, "invalid json"
    return status, data if isinstance(data, dict) else None, ""


def _error_detail(raw: bytes) -> str:
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        return ""
    if isinstance(data, dict) and isinstance(data.get("detail"), str):
        return data["detail"]
    return ""
