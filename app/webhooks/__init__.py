"""Webhook registry and outbound retry queue.

Public facade — keep imports stable for API, sinks, and camera sync.
"""

from __future__ import annotations

from app.webhooks.models import Webhook
from app.webhooks.queue import enqueue_payload, resend_event, retry_job
from app.webhooks.repository import (
    authenticate_webhook_login,
    create_webhook,
    delete_webhook,
    get_webhook,
    list_enabled_webhooks,
    list_webhooks,
    seed_webhooks_from_settings,
    update_webhook,
)
from app.webhooks.worker import OutboundWorker, get_outbound_worker

__all__ = [
    "OutboundWorker",
    "Webhook",
    "authenticate_webhook_login",
    "create_webhook",
    "delete_webhook",
    "enqueue_payload",
    "get_outbound_worker",
    "get_webhook",
    "list_enabled_webhooks",
    "list_webhooks",
    "resend_event",
    "retry_job",
    "seed_webhooks_from_settings",
    "update_webhook",
]
