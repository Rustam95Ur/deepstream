"""Opaque keyset cursors for list endpoints."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException


class CursorError(ValueError):
    pass


def encode_cursor(**parts: Any) -> str:
    raw = json.dumps(parts, separators=(",", ":"), default=str).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    pad = "=" * (-len(text) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(text + pad))
    except (ValueError, json.JSONDecodeError) as exc:
        raise CursorError("bad cursor") from exc
    if not isinstance(data, dict):
        raise CursorError("bad cursor")
    return data


def cursor_or_400(raw: str) -> dict[str, Any] | None:
    try:
        return decode_cursor(raw)
    except CursorError:
        raise HTTPException(status_code=400, detail="Некорректный курсор") from None


def cursor_id(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return None
    value = str(payload.get("id") or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="Некорректный курсор")
    return value


def cursor_str(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="Некорректный курсор")
    return value


def cursor_time(payload: dict[str, Any]) -> datetime:
    raw = payload.get("t")
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(status_code=400, detail="Некорректный курсор")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Некорректный курсор") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
