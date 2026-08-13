"""Queue trigger delivery off the GPU pipeline thread."""

from __future__ import annotations

import logging
import os
import threading
import time
from queue import Empty, Full, Queue
from typing import Any

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    return int(raw) if raw else default


class AsyncSink:
    """put_nowait from the pipeline; workers POST in the background."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.source_video = getattr(inner, "source_video", None)
        self._queue: Queue[dict[str, Any]] = Queue(
            maxsize=_env_int("NEXUS_DS_SINK_QUEUE", 10000)
        )
        self._stop = threading.Event()
        self._dropped = 0
        n = max(1, _env_int("NEXUS_DS_SINK_WORKERS", 4))
        self._threads = [
            threading.Thread(target=self._loop, name=f"sink-worker-{i}", daemon=True)
            for i in range(n)
        ]
        for t in self._threads:
            t.start()

    def send(self, payload: dict[str, Any]) -> str | None:
        try:
            self._queue.put_nowait(dict(payload))
        except Full:
            self._dropped += 1
            if self._dropped % 100 == 1:
                logger.error("outbound sink queue full, dropped=%s", self._dropped)
            return None
        return str(payload.get("event_id") or "") or None

    def close(self) -> None:
        deadline = time.monotonic() + float(
            os.environ.get("NEXUS_DS_SINK_CLOSE_S") or 120
        )
        while not self._queue.empty() and time.monotonic() < deadline:
            time.sleep(0.2)
        self._stop.set()
        remain = max(5.0, deadline - time.monotonic())
        for t in self._threads:
            t.join(timeout=remain)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                payload = self._queue.get(timeout=0.2)
            except Empty:
                continue
            try:
                self.inner.send(payload)
            except Exception:
                logger.exception("async sink worker failed")
