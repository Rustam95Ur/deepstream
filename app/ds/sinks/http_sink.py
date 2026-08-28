"""HTTP POST helper for signed webhook delivery."""

from __future__ import annotations

import http.client
import json
import logging
import ssl
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

logger = logging.getLogger(__name__)


def _request_post(
    url: str,
    body: bytes,
    *,
    headers: dict[str, str] | None = None,
    timeout_sec: float = 5.0,
) -> tuple[bool, int | None, str, bytes]:
    target = (url or "").strip()
    if not target:
        return False, None, "url empty", b""
    parsed = urlparse(target)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False, None, "url must be http(s)", b""
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
        raw = resp.read() or b""
        status = int(resp.status)
        if status >= 400:
            text = raw.decode("utf-8", errors="replace").strip()
            text = " ".join(text.split())
            if len(text) > 400:
                text = text[:397] + "..."
            detail = f"HTTP {status}"
            if text:
                detail = f"{detail}: {text}"
            logger.warning(
                "webhook POST url=%s status=%s body=%s",
                target,
                status,
                text[:200],
            )
            return False, status, detail, raw
        return True, status, "", raw
    except Exception as exc:
        logger.warning("webhook POST failed url=%s error=%s", target, exc)
        return False, None, str(exc), b""
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def post_bytes(
    url: str,
    body: bytes,
    *,
    headers: dict[str, str] | None = None,
    timeout_sec: float = 5.0,
) -> tuple[bool, int | None, str]:
    ok, status, error, _raw = _request_post(
        url, body, headers=headers, timeout_sec=timeout_sec
    )
    return ok, status, error


def build_multipart(
    fields: dict[str, str],
    *,
    files: dict[str, tuple[str, bytes, str]] | None = None,
) -> tuple[bytes, str]:
    """Return ``(body, content_type)`` for ``multipart/form-data``."""
    boundary = f"----nexus{uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{name}"\r\n'
                "Content-Type: application/json; charset=utf-8\r\n\r\n"
            ).encode()
        )
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")
    for name, (filename, data, content_type) in (files or {}).items():
        safe_name = (
            "".join(c if c.isalnum() or c in "._-" else "_" for c in filename)
            or "clip.mp4"
        )
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{safe_name}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode()
        )
        chunks.append(data)
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def post_json(
    url: str,
    body: bytes,
    *,
    headers: dict[str, str] | None = None,
    timeout_sec: float = 5.0,
) -> tuple[bool, int | None, str]:
    return post_bytes(
        url,
        body,
        headers={
            **(headers or {}),
            "Content-Type": "application/json",
        },
        timeout_sec=timeout_sec,
    )


def post_json_data(
    url: str,
    body: bytes,
    *,
    headers: dict[str, str] | None = None,
    timeout_sec: float = 5.0,
) -> tuple[bool, int | None, str, dict[str, Any] | None]:
    """Like ``post_json``, plus parsed JSON object on HTTP success."""
    ok, status, error, raw = _request_post(
        url,
        body,
        headers={**(headers or {}), "Content-Type": "application/json"},
        timeout_sec=timeout_sec,
    )
    if not ok:
        return False, status, error, None
    text = (raw or b"").decode("utf-8", errors="replace").strip()
    if not text:
        return True, status, "", None
    try:
        data = json.loads(text)
    except ValueError:
        return True, status, "", None
    return True, status, "", data if isinstance(data, dict) else None


def post_multipart(
    url: str,
    *,
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]] | None = None,
    headers: dict[str, str] | None = None,
    timeout_sec: float = 5.0,
) -> tuple[bool, int | None, str]:
    body, content_type = build_multipart(fields, files=files)
    return post_bytes(
        url,
        body,
        headers={
            **(headers or {}),
            "Content-Type": content_type,
        },
        timeout_sec=timeout_sec,
    )


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
        from app.history import record_send

        event_id = str(payload.get("event_id") or "")
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
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
