"""API package. Auth dependencies live in ``app.api.deps``."""

from __future__ import annotations

from app.api.deps import (
    ApiAuth,
    CameraApiAuth,
    LicenseAuth,
    require_api_token,
    require_camera_auth,
)

__all__ = [
    "ApiAuth",
    "CameraApiAuth",
    "LicenseAuth",
    "require_api_token",
    "require_camera_auth",
]
