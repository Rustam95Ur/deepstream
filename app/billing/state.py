"""Persisted license state and FastAPI license guard."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from app.billing.models import LICENSE_LOCKED, REASON_LABELS, BillingCheck
from app.settings import NodeSettings
from app.storage import get_store

logger = logging.getLogger(__name__)

_last: BillingCheck | None = None
_last_mtime: float = 0.0
_lock = threading.Lock()


def license_path() -> Path:
    return get_store().data_dir / "license.json"


def _parse_checked_at(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def check_from_dict(raw: dict[str, Any]) -> BillingCheck:
    return BillingCheck(
        url=str(raw.get("url") or ""),
        motherboard_serial=str(raw.get("motherboard_serial") or ""),
        api_key_configured=bool(raw.get("api_key_configured")),
        valid=bool(raw.get("valid")),
        reason=str(raw.get("reason") or ""),
        destroy=bool(raw.get("destroy")),
        client_name=str(raw.get("client_name") or ""),
        module=str(raw.get("module") or ""),
        checked_at=_parse_checked_at(raw.get("checked_at")),
    )


def persist(check: BillingCheck) -> float:
    path = license_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(check.as_dict())
    if payload.get("checked_at") is not None:
        payload["checked_at"] = check.checked_at.isoformat() if check.checked_at else None
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _load_persisted() -> tuple[BillingCheck | None, float]:
    path = license_path()
    try:
        mtime = path.stat().st_mtime
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, 0.0
    if not isinstance(raw, dict):
        return None, mtime
    return check_from_dict(raw), mtime


def last_billing_check() -> BillingCheck | None:
    global _last, _last_mtime
    path = license_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    with _lock:
        if _last is not None and mtime == _last_mtime:
            return _last
    loaded, file_mtime = _load_persisted()
    with _lock:
        if loaded is not None:
            _last = loaded
            _last_mtime = file_mtime
        elif mtime == 0.0:
            return _last
        return _last


def remember(check: BillingCheck) -> BillingCheck:
    global _last, _last_mtime
    mtime = persist(check)
    with _lock:
        _last = check
        _last_mtime = mtime
    return check


def license_ok() -> bool:
    check = last_billing_check()
    return bool(check and check.valid)


def license_reason() -> str:
    check = last_billing_check()
    if check is None:
        return "not_checked"
    if check.valid:
        return ""
    return check.reason or "invalid"


def license_lock_detail() -> str:
    reason = license_reason()
    label = REASON_LABELS.get(reason, reason)
    if label:
        return f"{LICENSE_LOCKED} ({label})"
    return LICENSE_LOCKED


def require_valid_license() -> None:
    if license_ok():
        return
    from fastapi import HTTPException, status

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=license_lock_detail(),
    )


def billing_status(settings: NodeSettings | None = None) -> BillingCheck:
    from app.billing.validate import billing_api_key, billing_url, motherboard_serial

    last = last_billing_check()
    if last is not None:
        return last
    cfg = settings or get_store().get_settings()
    return BillingCheck(
        url=billing_url(cfg),
        motherboard_serial=motherboard_serial(),
        api_key_configured=bool(billing_api_key(cfg)),
        valid=False,
        reason="not_checked",
    )
