"""POST api_key + motherboard serial to Nexus Billing."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.billing.models import BillingCheck
from app.billing.state import remember
from app.ds.sinks.http_sink import post_json_data
from app.env import env_str
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


def billing_url(settings: NodeSettings) -> str:
    return (
        (settings.billing_url or "").strip()
        or env_str("NEXUS_DS_BILLING_URL")
        or DEFAULT_BILLING_VALIDATE_URL
    )


def billing_api_key(settings: NodeSettings) -> str:
    return (settings.billing_api_key or "").strip() or env_str("NEXUS_DS_BILLING_API_KEY")


def settings_for_check(
    settings: NodeSettings | None = None,
    *,
    billing_url: str | None = None,  # noqa: A002 — API override field name
    billing_api_key: str | None = None,  # noqa: A002
) -> NodeSettings:
    cfg = settings or get_store().get_settings()
    url_override = billing_url
    key_override = billing_api_key
    if url_override is None and key_override is None:
        return cfg
    data = cfg.model_dump()
    if url_override is not None:
        data["billing_url"] = url_override
    if key_override is not None:
        data["billing_api_key"] = key_override
    return NodeSettings.model_validate(data)


def validate_billing_key(settings: NodeSettings | None = None) -> BillingCheck:
    """POST api_key + motherboard serial to Nexus Billing. Never raises."""
    cfg = settings or get_store().get_settings()
    url = billing_url(cfg)
    api_key = billing_api_key(cfg)
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
        return remember(check)

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
        return remember(check)

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
    return remember(check)
