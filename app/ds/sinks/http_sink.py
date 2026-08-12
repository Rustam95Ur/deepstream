"""HTTP POST trigger sink with keep-alive. Called from outbound worker threads."""

from __future__ import annotations

import http.client
import json
import logging
import ssl
import threading
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class HttpSink:
    def __init__(
        self,
        url: str,
        *,
        timeout_sec: float = 5.0,
        token: str = "",
        source_video: str | None = None,
    ) -> None:
        self.url = (url or "").strip()
        self.timeout_sec = timeout_sec
        self.token = (token or "").strip()
        self.source_video = source_video
        self._lock = threading.Lock()
        self._conn: http.client.HTTPConnection | None = None
        parsed = urlparse(self.url)
        self._https = parsed.scheme == "https"
        self._host = parsed.hostname or ""
        self._port = parsed.port or (443 if self._https else 80)
        self._path = parsed.path or "/"
        if parsed.query:
            self._path = f"{self._path}?{parsed.query}"

    def _connect(self) -> http.client.HTTPConnection:
        if self._https:
            ctx = ssl.create_default_context()
            conn: http.client.HTTPConnection = http.client.HTTPSConnection(
                self._host,
                self._port,
                timeout=self.timeout_sec,
                context=ctx,
            )
        else:
            conn = http.client.HTTPConnection(
                self._host,
                self._port,
                timeout=self.timeout_sec,
            )
        return conn

    def _reset(self) -> None:
        conn = self._conn
        self._conn = None
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    def send(self, payload: dict[str, Any]) -> str | None:
        if not self.url:
            logger.warning("HttpSink: triggers_url empty — skip")
            from app.history import record_send

            record_send(
                event_id=str(payload.get("event_id") or ""),
                sink="http",
                url="",
                status="skipped",
                error="triggers_url empty",
            )
            return None
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "nexus-deepstream/0.1",
            "Host": self._host,
            "Connection": "keep-alive",
            "Content-Length": str(len(body)),
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        event_id = str(payload.get("event_id") or "")
        try:
            with self._lock:
                if self._conn is None:
                    self._conn = self._connect()
                try:
                    self._conn.request("POST", self._path, body=body, headers=headers)
                    resp = self._conn.getresponse()
                    resp.read()
                    status = int(resp.status)
                except Exception:
                    self._reset()
                    raise
            if status >= 400:
                from app.history import record_send

                record_send(
                    event_id=event_id,
                    sink="http",
                    url=self.url,
                    status="error",
                    http_status=status,
                    error=f"HTTP {status}",
                )
                raise RuntimeError(f"HTTP trigger failed status={status}")
            logger.info(
                "HTTP trigger ok status=%s camera=%s type=%s event=%s",
                status,
                payload.get("camera_id"),
                payload.get("trigger_type"),
                event_id,
            )
            from app.history import record_send

            record_send(
                event_id=event_id,
                sink="http",
                url=self.url,
                status="ok",
                http_status=status,
            )
            return event_id
        except Exception as exc:
            if not isinstance(exc, RuntimeError):
                from app.history import record_send

                record_send(
                    event_id=event_id,
                    sink="http",
                    url=self.url,
                    status="error",
                    error=str(exc),
                )
                logger.exception("HTTP trigger failed url=%s", self.url)
            raise
