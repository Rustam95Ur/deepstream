"""Tear down this compose project's containers when billing returns destroy=true."""

from __future__ import annotations

import http.client
import json
import logging
import os
import socket
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DOCKER_SOCK = Path(os.environ.get("NEXUS_DS_DOCKER_SOCK") or "/var/run/docker.sock")
_NAME_PREFIX = (os.environ.get("NEXUS_DS_DESTROY_NAME_PREFIX") or "nexus-deepstream").strip()
_started = False
_lock = threading.Lock()


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, sock_path: str, timeout: float = 30.0) -> None:
        super().__init__("localhost", timeout=timeout)
        self._sock_path = sock_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self._sock_path)
        self.sock = sock


def _docker_request(
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    timeout: float = 60.0,
) -> tuple[int, Any]:
    if not _DOCKER_SOCK.exists():
        raise RuntimeError(f"docker socket missing: {_DOCKER_SOCK}")
    headers = {"Host": "localhost", "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(body))
    conn = _UnixHTTPConnection(str(_DOCKER_SOCK), timeout=timeout)
    try:
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        raw = resp.read() or b""
        status = int(resp.status)
        if not raw:
            return status, None
        try:
            return status, json.loads(raw.decode("utf-8"))
        except ValueError:
            return status, raw.decode("utf-8", errors="replace")
    finally:
        conn.close()


def _own_compose_project() -> str:
    override = (os.environ.get("NEXUS_DS_COMPOSE_PROJECT") or "").strip()
    if override:
        return override
    hostname = socket.gethostname().strip()
    if not hostname:
        return ""
    try:
        status, data = _docker_request("GET", f"/containers/{hostname}/json")
    except Exception:
        logger.warning("docker inspect self failed", exc_info=True)
        return ""
    if status >= 400 or not isinstance(data, dict):
        return ""
    labels = data.get("Config", {}).get("Labels") or data.get("Labels") or {}
    if not isinstance(labels, dict):
        return ""
    return str(labels.get("com.docker.compose.project") or "").strip()


def _list_target_containers(project: str) -> list[dict[str, Any]]:
    filters: dict[str, list[str]] = {}
    if project:
        filters["label"] = [f"com.docker.compose.project={project}"]
    query = "all=true"
    if filters:
        query += "&filters=" + urllib.parse.quote(json.dumps(filters))
    status, data = _docker_request("GET", f"/containers/json?{query}")
    if status >= 400:
        raise RuntimeError(f"docker list containers failed: HTTP {status} {data}")
    rows = data if isinstance(data, list) else []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        names = row.get("Names") or []
        name = ""
        if isinstance(names, list) and names:
            name = str(names[0]).lstrip("/")
        labels = row.get("Labels") or {}
        label_project = ""
        if isinstance(labels, dict):
            label_project = str(labels.get("com.docker.compose.project") or "")
        if project and label_project == project:
            out.append(row)
            continue
        if not project and name.startswith(_NAME_PREFIX):
            out.append(row)
    if project and not out and _NAME_PREFIX:
        # Fallback if labels are missing but fixed container_name prefix is used.
        status, all_rows = _docker_request("GET", "/containers/json?all=true")
        if status < 400 and isinstance(all_rows, list):
            for row in all_rows:
                if not isinstance(row, dict):
                    continue
                names = row.get("Names") or []
                name = str(names[0]).lstrip("/") if names else ""
                if name.startswith(_NAME_PREFIX):
                    out.append(row)
    return out


def _remove_container(container_id: str, name: str) -> None:
    status, data = _docker_request(
        "DELETE",
        f"/containers/{container_id}?force=true&v=false",
        timeout=120.0,
    )
    if status >= 400 and status != 404:
        logger.error(
            "failed to remove container id=%s name=%s status=%s body=%s",
            container_id[:12],
            name or "-",
            status,
            data,
        )
        return
    logger.warning("removed container id=%s name=%s", container_id[:12], name or "-")


def destroy_project_containers(*, reason: str = "") -> int:
    """Force-remove all containers of this compose project. Returns count removed."""
    project = _own_compose_project()
    logger.critical(
        "billing destroy requested reason=%s project=%s prefix=%s",
        reason or "-",
        project or "-",
        _NAME_PREFIX or "-",
    )
    containers = _list_target_containers(project)
    if not containers:
        logger.critical("billing destroy: no matching containers found")
        return 0
    # Remove self last so the destroy can finish.
    hostname = socket.gethostname().strip()
    ordered = sorted(
        containers,
        key=lambda row: 1 if str(row.get("Id") or "").startswith(hostname) else 0,
    )
    removed = 0
    for row in ordered:
        cid = str(row.get("Id") or "").strip()
        if not cid:
            continue
        names = row.get("Names") or []
        name = str(names[0]).lstrip("/") if isinstance(names, list) and names else ""
        try:
            _remove_container(cid, name)
            removed += 1
        except Exception:
            logger.exception("billing destroy failed for %s", name or cid[:12])
    logger.critical("billing destroy finished removed=%s", removed)
    return removed


def schedule_project_destroy(*, reason: str = "", delay_s: float = 2.0) -> bool:
    """Start background teardown once. Returns False if already scheduled."""
    global _started
    with _lock:
        if _started:
            return False
        _started = True

    def _run() -> None:
        if delay_s > 0:
            time.sleep(delay_s)
        try:
            destroy_project_containers(reason=reason)
        except Exception:
            logger.exception("billing destroy aborted")

    threading.Thread(target=_run, name="billing-destroy", daemon=True).start()
    return True
