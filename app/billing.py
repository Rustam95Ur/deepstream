"""Validate this node's API key against Nexus Billing."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.ds.sinks.http_sink import post_json_data
from app.settings import DEFAULT_BILLING_VALIDATE_URL, NodeSettings
from app.storage import get_store

logger = logging.getLogger(__name__)

_PLACEHOLDER_SERIALS = frozenset(
    {
        "",
        "none",
        "not specified",
        "not available",
        "to be filled by o.e.m.",
        "default string",
        "system serial number",
    }
)


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


LICENSE_LOCKED = "Лицензия недействительна. Pipeline и доступ к ноде отключены."

_REASON_LABELS = {
    "missing_api_key": "ключ не задан",
    "not_checked": "ещё не проверялся",
    "key_not_found": "ключ не найден",
    "client_inactive": "клиент отключён",
    "subscription_expired": "подписка истекла",
    "stolen_key": "ключ привязан к другой плате",
    "invalid": "ключ отклонён",
}

_last: BillingCheck | None = None
_last_mtime: float = 0.0
_runtime_locked = True
_lock = threading.Lock()


def _license_path() -> Path:
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


def _check_from_dict(raw: dict[str, Any]) -> BillingCheck:
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


def _persist(check: BillingCheck) -> float:
    path = _license_path()
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
    path = _license_path()
    try:
        mtime = path.stat().st_mtime
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, 0.0
    if not isinstance(raw, dict):
        return None, mtime
    return _check_from_dict(raw), mtime


def _is_video_role() -> bool:
    return (os.environ.get("NEXUS_DS_ROLE") or "").strip().lower() == "video"


def motherboard_serial() -> str:
    for path in (
        Path("/sys/class/dmi/id/board_serial"),
        Path("/sys/class/dmi/id/product_serial"),
    ):
        try:
            raw = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if raw and raw.casefold() not in _PLACEHOLDER_SERIALS:
            return raw
    if os.name == "nt":
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-CimInstance Win32_BaseBoard).SerialNumber",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            raw = (result.stdout or "").strip()
            if raw and raw.casefold() not in _PLACEHOLDER_SERIALS:
                return raw
        except (OSError, subprocess.SubprocessError):
            pass
    return ""


def last_billing_check() -> BillingCheck | None:
    global _last, _last_mtime
    path = _license_path()
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


def _remember(check: BillingCheck) -> BillingCheck:
    global _last, _last_mtime
    mtime = _persist(check)
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
    label = _REASON_LABELS.get(reason, reason)
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


def _maybe_destroy_project(check: BillingCheck) -> None:
    if check.valid or not check.destroy:
        return
    from app.docker_destroy import schedule_project_destroy

    logger.critical(
        "billing destroy=true reason=%s — scheduling compose teardown",
        check.reason or "-",
    )
    schedule_project_destroy(reason=check.reason or "destroy")


def apply_runtime_lock(check: BillingCheck | None = None) -> BillingCheck:
    """Stop or restore pipeline/ring based on the last billing check."""
    global _runtime_locked
    row = check or last_billing_check() or validate_billing_key()
    if row.valid:
        was_locked = _runtime_locked
        _runtime_locked = False
        if was_locked:
            _unlock_runtime()
        return row
    _runtime_locked = True
    _lock_runtime(row)
    _maybe_destroy_project(row)
    return row


def _lock_runtime(check: BillingCheck) -> None:
    logger.warning(
        "license lock reason=%s — stopping pipeline and ring-buffer",
        check.reason or "invalid",
    )
    if _is_video_role():
        try:
            from app.worker import get_manager

            get_manager().stop()
        except Exception:
            logger.warning("license lock: pipeline stop failed", exc_info=True)
        try:
            from app.ds.ring_buffer import get_ring_buffer

            get_ring_buffer().stop()
        except Exception:
            logger.warning("license lock: ring-buffer stop failed", exc_info=True)
        return
    try:
        from app.video_client import video_configured, worker_stop

        if video_configured():
            worker_stop()
    except Exception:
        logger.warning("license lock: video stop failed", exc_info=True)


def _unlock_runtime() -> None:
    settings = get_store().get_settings()
    if _is_video_role():
        try:
            from app.ds.ring_buffer import get_ring_buffer

            get_ring_buffer().start()
        except Exception:
            logger.warning("license unlock: ring-buffer start failed", exc_info=True)
        if settings.auto_start_pipeline:
            try:
                from app.worker import get_manager

                get_manager().start()
            except Exception:
                logger.warning("license unlock: pipeline start failed", exc_info=True)
        return
    if not settings.auto_start_pipeline:
        return
    try:
        from app.video_client import video_configured, worker_start

        if video_configured():
            worker_start()
    except Exception:
        logger.warning("license unlock: video start failed", exc_info=True)


def billing_status(settings: NodeSettings | None = None) -> BillingCheck:
    last = last_billing_check()
    if last is not None:
        return last
    cfg = settings or get_store().get_settings()
    return BillingCheck(
        url=_billing_url(cfg),
        motherboard_serial=motherboard_serial(),
        api_key_configured=bool(_billing_api_key(cfg)),
        valid=False,
        reason="not_checked",
    )


def settings_for_check(
    settings: NodeSettings | None = None,
    *,
    billing_url: str | None = None,
    billing_api_key: str | None = None,
) -> NodeSettings:
    cfg = settings or get_store().get_settings()
    if billing_url is None and billing_api_key is None:
        return cfg
    data = cfg.model_dump()
    if billing_url is not None:
        data["billing_url"] = billing_url
    if billing_api_key is not None:
        data["billing_api_key"] = billing_api_key
    return NodeSettings.model_validate(data)


def _billing_url(settings: NodeSettings) -> str:
    return (
        (settings.billing_url or "").strip()
        or (os.environ.get("NEXUS_DS_BILLING_URL") or "").strip()
        or DEFAULT_BILLING_VALIDATE_URL
    )


def _billing_api_key(settings: NodeSettings) -> str:
    return (
        (settings.billing_api_key or "").strip()
        or (os.environ.get("NEXUS_DS_BILLING_API_KEY") or "").strip()
    )


def validate_billing_key(settings: NodeSettings | None = None) -> BillingCheck:
    """POST api_key + motherboard serial to Nexus Billing. Never raises."""
    cfg = settings or get_store().get_settings()
    url = _billing_url(cfg)
    api_key = _billing_api_key(cfg)
    serial = motherboard_serial()
    now = datetime.now(timezone.utc)
    if not api_key:
        check = BillingCheck(
            url=url,
            motherboard_serial=serial,
            api_key_configured=False,
            valid=False,
            reason="missing_api_key",
            checked_at=now,
        )
        return _remember(check)

    body = json.dumps(
        {"api_key": api_key, "motherboard_serial": serial},
        ensure_ascii=False,
    ).encode("utf-8")
    ok, status, error, data = post_json_data(
        url,
        body,
        timeout_sec=float(cfg.billing_timeout_sec or 5.0),
    )
    if not ok or not isinstance(data, dict):
        check = BillingCheck(
            url=url,
            motherboard_serial=serial,
            api_key_configured=True,
            valid=False,
            reason=error or (f"HTTP {status}" if status else "billing unreachable"),
            checked_at=now,
        )
        logger.warning("billing validate failed url=%s error=%s", url, check.reason)
        return _remember(check)

    valid = bool(data.get("valid"))
    reason = str(data.get("reason") or "").strip()
    destroy = bool(data.get("destroy"))
    if not valid and not reason:
        reason = "invalid"
    if reason == "stolen_key":
        destroy = True
    check = BillingCheck(
        url=url,
        motherboard_serial=str(data.get("motherboard_serial") or serial),
        api_key_configured=True,
        valid=valid,
        reason=reason,
        destroy=destroy,
        client_name=str(data.get("client_name") or ""),
        module=str(data.get("module") or ""),
        checked_at=now,
    )
    if valid:
        logger.info(
            "billing key ok client=%s module=%s serial=%s",
            check.client_name or "-",
            check.module or "-",
            serial or "-",
        )
    else:
        logger.warning(
            "billing key rejected reason=%s destroy=%s serial=%s",
            reason,
            destroy,
            serial or "-",
        )
    return _remember(check)
