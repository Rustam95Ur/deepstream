"""Validate this node's API key against Nexus Billing (stable facade)."""

from __future__ import annotations

from app.billing.models import LICENSE_LOCKED, REASON_LABELS, BillingCheck
from app.billing.runtime_lock import (
    ApiVideoClientLock,
    VideoLocalLock,
    apply_runtime_lock,
    get_runtime_lock,
    is_video_role,
)
from app.billing.state import (
    billing_status,
    last_billing_check,
    license_lock_detail,
    license_ok,
    license_reason,
    require_valid_license,
)
from app.billing.validate import (
    motherboard_serial,
    settings_for_check,
    validate_billing_key,
)

__all__ = [
    "ApiVideoClientLock",
    "BillingCheck",
    "LICENSE_LOCKED",
    "REASON_LABELS",
    "VideoLocalLock",
    "apply_runtime_lock",
    "billing_status",
    "get_runtime_lock",
    "is_video_role",
    "last_billing_check",
    "license_lock_detail",
    "license_ok",
    "license_reason",
    "motherboard_serial",
    "require_valid_license",
    "settings_for_check",
    "validate_billing_key",
]
