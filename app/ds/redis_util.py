"""Shared Redis helpers (optional Celery sink)."""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlparse


def parse_redis_url(url: str) -> tuple[str, int, str | None, int, bool]:
    parsed = urlparse(url)
    if parsed.scheme not in ("redis", "rediss"):
        raise ValueError(f"unsupported broker scheme: {parsed.scheme}")
    host = parsed.hostname or "localhost"
    port = int(parsed.port or 6379)
    password = unquote(parsed.password) if parsed.password else None
    db = 0
    if parsed.path and parsed.path.strip("/"):
        db = int(parsed.path.strip("/").split("/")[0])
    ssl = parsed.scheme == "rediss"
    return host, port, password, db, ssl


def redis_client(url: str, *, decode_responses: bool = False) -> Any:
    try:
        import redis  # type: ignore
    except ImportError as exc:
        raise RuntimeError("redis package required for Celery sink") from exc

    broker = (url or "").strip()
    if not broker:
        raise RuntimeError("Redis broker URL is empty")

    host, port, password, db, ssl = parse_redis_url(broker)
    return redis.Redis(
        host=host,
        port=port,
        password=password,
        db=db,
        ssl=ssl,
        decode_responses=decode_responses,
        socket_connect_timeout=5,
        socket_timeout=5,
    )
