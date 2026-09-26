"""Stop / restore pipeline and ring-buffer based on license state.

Adapters:
- ``VideoLocalLock`` — in-process (role=video): PipelineManager + ring-buffer
- ``ApiVideoClientLock`` — API role: HTTP to video container

``docker_destroy`` stays isolated; only scheduled on destroy=true.
"""

from __future__ import annotations

import logging
from typing import Protocol

from app.billing.models import BillingCheck
from app.billing.state import last_billing_check
from app.env import env_str
from app.storage import get_store

logger = logging.getLogger(__name__)

_runtime_locked = True


def is_video_role() -> bool:
    return env_str("NEXUS_DS_ROLE").lower() == "video"


class RuntimeLock(Protocol):
    def lock(self, check: BillingCheck) -> None: ...

    def unlock(self) -> None: ...


class VideoLocalLock:
    """Lock/unlock GPU pipeline and ring-buffer in this process."""

    def lock(self, check: BillingCheck) -> None:
        logger.warning(
            "license lock reason=%s — stopping pipeline and ring-buffer",
            check.reason or "invalid",
        )
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

    def unlock(self) -> None:
        settings = get_store().get_settings()
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


class ApiVideoClientLock:
    """Lock/unlock via internal video HTTP control plane."""

    def lock(self, check: BillingCheck) -> None:
        logger.warning(
            "license lock reason=%s — stopping pipeline and ring-buffer",
            check.reason or "invalid",
        )
        try:
            from app.video_client import video_configured, worker_stop

            if video_configured():
                worker_stop()
        except Exception:
            logger.warning("license lock: video stop failed", exc_info=True)

    def unlock(self) -> None:
        settings = get_store().get_settings()
        if not settings.auto_start_pipeline:
            return
        try:
            from app.video_client import video_configured, worker_start

            if video_configured():
                worker_start()
        except Exception:
            logger.warning("license unlock: video start failed", exc_info=True)


def get_runtime_lock() -> RuntimeLock:
    if is_video_role():
        return VideoLocalLock()
    return ApiVideoClientLock()


def maybe_destroy_project(check: BillingCheck) -> None:
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
    from app.billing.validate import validate_billing_key

    row = check or last_billing_check() or validate_billing_key()
    adapter = get_runtime_lock()
    if row.valid:
        was_locked = _runtime_locked
        _runtime_locked = False
        if was_locked:
            adapter.unlock()
        return row
    _runtime_locked = True
    adapter.lock(row)
    maybe_destroy_project(row)
    return row
