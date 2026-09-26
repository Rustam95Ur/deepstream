"""Pydantic API schemas (stable facade)."""

from __future__ import annotations

from app.schemas.cameras import (
    CameraIn,
    CameraListOut,
    CameraOut,
    CameraPatch,
    CameraTestBatchIn,
    CameraTestBatchOut,
)
from app.schemas.history import (
    ClipOut,
    ClipUrlOut,
    OutboundJobListOut,
    OutboundJobOut,
    ResendOut,
    SendEventOut,
    SendHistoryOut,
    TriggerEventDetailOut,
    TriggerEventOut,
    TriggerHistoryOut,
)
from app.schemas.node import (
    BillingCheckOut,
    BillingValidateIn,
    CameraSkipOut,
    HealthOut,
    LogLineOut,
    RingCameraHealthOut,
    VideoHealthOut,
    WorkerStatusOut,
)
from app.schemas.users import (
    LoginIn,
    SessionOut,
    UserIn,
    UserListOut,
    UserOut,
    UserUpdateIn,
)
from app.schemas.webhooks import (
    CameraSyncPushOut,
    CameraSyncWebhookResult,
    WebhookIn,
    WebhookListOut,
    WebhookOut,
)

__all__ = [
    "BillingCheckOut",
    "BillingValidateIn",
    "CameraIn",
    "CameraListOut",
    "CameraOut",
    "CameraPatch",
    "CameraSkipOut",
    "CameraSyncPushOut",
    "CameraSyncWebhookResult",
    "CameraTestBatchIn",
    "CameraTestBatchOut",
    "ClipOut",
    "ClipUrlOut",
    "HealthOut",
    "LogLineOut",
    "LoginIn",
    "OutboundJobListOut",
    "OutboundJobOut",
    "ResendOut",
    "RingCameraHealthOut",
    "SendEventOut",
    "SendHistoryOut",
    "SessionOut",
    "TriggerEventDetailOut",
    "TriggerEventOut",
    "TriggerHistoryOut",
    "UserIn",
    "UserListOut",
    "UserOut",
    "UserUpdateIn",
    "VideoHealthOut",
    "WebhookIn",
    "WebhookListOut",
    "WebhookOut",
    "WorkerStatusOut",
]
