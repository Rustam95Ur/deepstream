"""Background outbound webhook worker.

API and video both call ``get_outbound_worker().start()``. Dual start is
intentional: claim uses ``FOR UPDATE SKIP LOCKED``, so either process can
deliver without double-processing the same job.
"""

from __future__ import annotations

import logging
import threading

from sqlalchemy.exc import SQLAlchemyError

from app.db import db_enabled
from app.storage import get_store
from app.webhooks.delivery import claim_jobs, process_job

logger = logging.getLogger(__name__)


class OutboundWorker:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="outbound-webhooks", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=5.0)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                from app.billing import license_ok

                if (
                    db_enabled()
                    and get_store().get_settings().enable_http_sink
                    and license_ok()
                ):
                    ids = claim_jobs()
                    for job_id in ids:
                        try:
                            process_job(job_id)
                        except Exception:
                            logger.exception("outbound job failed id=%s", job_id)
            except SQLAlchemyError:
                logger.exception("outbound worker db error")
            except Exception:
                logger.exception("outbound worker failed")
            self._stop.wait(0.5)


_worker: OutboundWorker | None = None


def get_outbound_worker() -> OutboundWorker:
    global _worker
    if _worker is None:
        _worker = OutboundWorker()
    return _worker
