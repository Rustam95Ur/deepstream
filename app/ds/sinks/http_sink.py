"""HTTP POST helper for signed webhook delivery."""

from __future__ import annotations

import http.client
import logging
import ssl
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def post_json(
    url: str,
    body: bytes,
    *,
    headers: dict[str, str] | None = None,
    timeout_sec: float = 5.0,
) -> tuple[bool, int | None, str]:
    target = (url or "").strip()
    if not target:
        return False, None, "url empty"
    parsed = urlparse(target)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False, None, "url must be http(s)"
    https = parsed.scheme == "https"
    host = parsed.hostname
    port = parsed.port or (443 if https else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    req_headers = {
        "Host": host,
        "Connection": "close",
        "Content-Length": str(len(body)),
        **(headers or {}),
    }
    conn: http.client.HTTPConnection | None = None
    try:
        if https:
            conn = http.client.HTTPSConnection(
                host,
                port,
                timeout=timeout_sec,
                context=ssl.create_default_context(),
            )
        else:
            conn = http.client.HTTPConnection(host, port, timeout=timeout_sec)
        conn.request("POST", path, body=body, headers=req_headers)
        resp = conn.getresponse()
        resp.read()
        status = int(resp.status)
        if status >= 400:
            return False, status, f"HTTP {status}"
        return True, status, ""
    except Exception as exc:
        logger.warning("webhook POST failed url=%s error=%s", target, exc)
        return False, None, str(exc)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


class HttpSink:
    """Legacy single-URL sink kept for tests / local wiring."""

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

    def send(self, payload: dict[str, Any]) -> str | None:
        import json

        from app.history import record_send

        event_id = str(payload.get("event_id") or "")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "nexus-deepstream/0.1",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        ok, status, error = post_json(
            self.url, body, headers=headers, timeout_sec=self.timeout_sec
        )
        record_send(
            event_id=event_id,
            sink="http",
            url=self.url,
            status="ok" if ok else "error",
            http_status=status,
            error="" if ok else error,
        )
        if not ok:
            raise RuntimeError(error or "HTTP trigger failed")
        return event_id or None
