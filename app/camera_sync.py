"""Push local cameras to Campus / nexus_incidents via configured webhooks."""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.billing import license_lock_detail, license_ok
from app.ds.sinks.http_sink import post_json_data
from app.storage import get_store
from app.webhooks import list_enabled_webhooks

logger = logging.getLogger(__name__)

_SYNC_TIMEOUT_S = 30.0


def cameras_sync_url(webhook_url: str) -> str:
    """Map incident ingest URL to ``POST /api/v1/cameras/sync``."""
    raw = (webhook_url or "").strip()
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    path = (parsed.path or "").rstrip("/")
    replacements = (
        ("/api/v1/incidents", "/api/v1/cameras/sync"),
        ("/api/v1/school/incident-ingest", "/api/v1/cameras/sync"),
        ("/incident-ingest", "/cameras/sync"),
        ("/incidents", "/cameras/sync"),
    )
    new_path = ""
    for suffix, dest in replacements:
        if path.endswith(suffix):
            new_path = f"{path[: -len(suffix)]}{dest}"
            break
    if not new_path:
        new_path = "/api/v1/cameras/sync"
    return urlunsplit((parsed.scheme, parsed.netloc, new_path, "", ""))


def build_camera_sync_payload() -> dict[str, Any]:
    store = get_store()
    settings = store.get_settings()
    cameras = []
    for cam in store.list_cameras():
        cameras.append(
            {
                "id": cam.id,
                "name": cam.name or cam.id,
                "main_uri": cam.main_uri,
                "rtsp_url": cam.main_uri,
                "enabled": bool(cam.enabled),
                "external_id": cam.external_id or "",
            }
        )
    return {
        "source": "nexus_deepstream",
        "node_id": (settings.node_id or "").strip() or "ds-1",
        "node_name": (settings.node_name or "").strip(),
        "cameras": cameras,
    }


def push_cameras_to_webhooks() -> dict[str, Any]:
    payload = build_camera_sync_payload()
    if not license_ok():
        return {
            "ok": False,
            "node_id": payload["node_id"],
            "cameras": len(payload["cameras"]),
            "results": [],
            "error": license_lock_detail(),
        }
    if not get_store().get_settings().enable_http_sink:
        return {
            "ok": False,
            "node_id": payload["node_id"],
            "cameras": len(payload["cameras"]),
            "results": [],
            "error": "отправка по HTTP выключена",
        }
    hooks = [h for h in list_enabled_webhooks() if (h.url or "").strip()]
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    results: list[dict[str, Any]] = []
    if not hooks:
        return {
            "ok": False,
            "node_id": payload["node_id"],
            "cameras": len(payload["cameras"]),
            "results": [],
            "error": "нет включённых webhook’ов",
        }

    headers = {
        "User-Agent": "nexus-deepstream/0.1",
        "X-Nexus-Node-Id": str(payload["node_id"]),
    }
    for hook in hooks:
        url = cameras_sync_url(hook.url)
        if not url:
            results.append(
                {
                    "webhook_id": hook.id,
                    "webhook_name": hook.name,
                    "url": hook.url,
                    "ok": False,
                    "created": 0,
                    "updated": 0,
                    "skipped": 0,
                    "error": "некорректный URL webhook",
                }
            )
            continue
        timeout = max(_SYNC_TIMEOUT_S, float(hook.timeout_sec or 5.0))
        ok, status, error, data = post_json_data(
            url, body, headers=headers, timeout_sec=timeout
        )
        created = int((data or {}).get("created") or 0) if ok else 0
        updated = int((data or {}).get("updated") or 0) if ok else 0
        skipped = int((data or {}).get("skipped") or 0) if ok else 0
        if ok:
            logger.info(
                "camera sync ok webhook=%s url=%s created=%s updated=%s skipped=%s",
                hook.name,
                url,
                created,
                updated,
                skipped,
            )
        else:
            logger.warning(
                "camera sync failed webhook=%s url=%s error=%s",
                hook.name,
                url,
                error,
            )
        results.append(
            {
                "webhook_id": hook.id,
                "webhook_name": hook.name,
                "url": url,
                "ok": ok,
                "http_status": status,
                "created": created,
                "updated": updated,
                "skipped": skipped,
                "error": "" if ok else (error or f"HTTP {status}"),
            }
        )

    return {
        "ok": all(row["ok"] for row in results) if results else False,
        "node_id": payload["node_id"],
        "cameras": len(payload["cameras"]),
        "results": results,
        "error": "",
    }
