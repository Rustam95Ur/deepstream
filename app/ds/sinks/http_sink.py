"""HTTP POST trigger sink (primary for multi-node product)."""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


class HttpSink:
    def __init__(
        self,
        url: str,
        *,
        timeout_sec: float = 10.0,
        token: str = "",
        source_video: str | None = None,
    ) -> None:
        self.url = (url or "").strip()
        self.timeout_sec = timeout_sec
        self.token = (token or "").strip()
        self.source_video = source_video

    def send(self, payload: dict[str, Any]) -> str | None:
        if not self.url:
            logger.warning("HttpSink: triggers_url empty — skip")
            return None
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": "nexus-deepstream/0.1",
            },
        )
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                status = getattr(resp, "status", 200)
                logger.info(
                    "HTTP trigger ok status=%s camera=%s type=%s event=%s",
                    status,
                    payload.get("camera_id"),
                    payload.get("trigger_type"),
                    payload.get("event_id"),
                )
                return str(payload.get("event_id") or "")
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:500] if exc.fp else b""
            logger.error(
                "HTTP trigger failed status=%s body=%s",
                exc.code,
                detail.decode("utf-8", errors="replace"),
            )
            raise
        except Exception:
            logger.exception("HTTP trigger failed url=%s", self.url)
            raise
