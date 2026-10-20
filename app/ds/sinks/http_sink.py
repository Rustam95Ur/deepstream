"""HTTP POST helper for signed webhook delivery."""

from __future__ import annotations

import base64
import http.client
import json
import logging
import ssl
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class HttpProxy:
    host: str
    port: int
    username: str = ""
    password: str = ""


@dataclass(frozen=True, slots=True)
class ConnectPlan:
    connect_host: str
    connect_port: int
    path: str
    tls: bool
    tunnel: tuple[str, int] | None = None
    tunnel_headers: dict[str, str] | None = None
    extra_headers: dict[str, str] | None = None


def proxy_from_settings(
    *,
    enabled: bool,
    host: str,
    port: int,
    username: str = "",
    password: str = "",
) -> tuple[HttpProxy | None, str]:
    """Build a proxy, or an error when it is enabled but incomplete."""
    if not enabled:
        return None, ""
    clean_host = (host or "").strip()
    clean_port = int(port or 0)
    if not clean_host or not (1 <= clean_port <= 65535):
        return None, "прокси включён, но не заданы хост или порт"
    return (
        HttpProxy(
            host=clean_host,
            port=clean_port,
            username=(username or "").strip(),
            password=password or "",
        ),
        "",
    )


def _proxy_authorization(proxy: HttpProxy) -> str:
    user = (proxy.username or "").strip()
    if not user:
        return ""
    raw = f"{user}:{proxy.password or ''}".encode("utf-8")
    token = base64.b64encode(raw).decode("ascii")
    return f"Basic {token}"


def connect_plan(url: str, proxy: HttpProxy | None = None) -> ConnectPlan | str:
    """How to open the socket. HTTPS via proxy uses CONNECT, HTTP uses an absolute URI."""
    target = (url or "").strip()
    if not target:
        return "url empty"
    parsed = urlparse(target)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return "url must be http(s)"
    https = parsed.scheme == "https"
    host = parsed.hostname
    port = parsed.port or (443 if https else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    if proxy is None:
        return ConnectPlan(connect_host=host, connect_port=port, path=path, tls=https)
    phost = (proxy.host or "").strip()
    pport = int(proxy.port or 0)
    if not phost or not (1 <= pport <= 65535):
        return "proxy host or port is invalid"
    auth = _proxy_authorization(proxy)
    if https:
        tunnel_headers = {"Proxy-Authorization": auth} if auth else None
        return ConnectPlan(
            connect_host=phost,
            connect_port=pport,
            path=path,
            tls=True,
            tunnel=(host, port),
            tunnel_headers=tunnel_headers,
        )
    netloc = f"{host}:{port}" if parsed.port else host
    extra = {"Proxy-Authorization": auth} if auth else None
    return ConnectPlan(
        connect_host=phost,
        connect_port=pport,
        path=f"http://{netloc}{path}",
        tls=False,
        extra_headers=extra,
    )


def _request_post(
    url: str,
    body: bytes,
    *,
    headers: dict[str, str] | None = None,
    timeout_sec: float = 5.0,
    proxy: HttpProxy | None = None,
) -> tuple[bool, int | None, str, bytes]:
    target = (url or "").strip()
    plan = connect_plan(target, proxy)
    if isinstance(plan, str):
        return False, None, plan, b""
    parsed = urlparse(target)
    host_header = parsed.hostname or ""
    if proxy is not None and parsed.port:
        host_header = f"{host_header}:{parsed.port}"
    req_headers = {
        "Host": host_header,
        "Connection": "close",
        "Content-Length": str(len(body)),
        **(plan.extra_headers or {}),
        **(headers or {}),
    }
    conn: http.client.HTTPConnection | None = None
    try:
        if plan.tls:
            conn = http.client.HTTPSConnection(
                plan.connect_host,
                plan.connect_port,
                timeout=timeout_sec,
                context=ssl.create_default_context(),
            )
            if plan.tunnel is not None:
                tunnel_host, tunnel_port = plan.tunnel
                if plan.tunnel_headers:
                    conn.set_tunnel(tunnel_host, tunnel_port, headers=plan.tunnel_headers)
                else:
                    conn.set_tunnel(tunnel_host, tunnel_port)
        else:
            conn = http.client.HTTPConnection(
                plan.connect_host, plan.connect_port, timeout=timeout_sec
            )
        conn.request("POST", plan.path, body=body, headers=req_headers)
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
    proxy: HttpProxy | None = None,
) -> tuple[bool, int | None, str]:
    ok, status, error, _raw = _request_post(
        url, body, headers=headers, timeout_sec=timeout_sec, proxy=proxy
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
    proxy: HttpProxy | None = None,
) -> tuple[bool, int | None, str]:
    return post_bytes(
        url,
        body,
        headers={
            **(headers or {}),
            "Content-Type": "application/json",
        },
        timeout_sec=timeout_sec,
        proxy=proxy,
    )


def post_json_data(
    url: str,
    body: bytes,
    *,
    headers: dict[str, str] | None = None,
    timeout_sec: float = 5.0,
    proxy: HttpProxy | None = None,
) -> tuple[bool, int | None, str, dict[str, Any] | None]:
    """Like ``post_json``, plus parsed JSON object on HTTP success."""
    ok, status, error, raw = _request_post(
        url,
        body,
        headers={**(headers or {}), "Content-Type": "application/json"},
        timeout_sec=timeout_sec,
        proxy=proxy,
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
    proxy: HttpProxy | None = None,
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
        proxy=proxy,
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
