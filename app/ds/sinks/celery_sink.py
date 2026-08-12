"""Send incident triggers to Django Celery over Redis broker (legacy)."""

from __future__ import annotations

import base64
import json
import logging
import uuid
from typing import Any

from app.ds.redis_util import redis_client

logger = logging.getLogger(__name__)

DEFAULT_TASK_NAME = "apps.school.tasks.process_deepstream_incident_trigger"


def remap_source_video_for_celery(path: str) -> str:
    raw = (path or "").strip()
    if not raw:
        return raw
    if raw.startswith("/data/deepstream/"):
        return "/app/project/media/deepstream/" + raw[len("/data/deepstream/") :]
    return raw


class CelerySink:
    """LPUSH Celery JSON task onto a Redis queue."""

    def __init__(
        self,
        broker_url_value: str,
        *,
        queue: str = "celery",
        task_name: str = DEFAULT_TASK_NAME,
        source_video: str | None = None,
        skip_celery: bool = False,
    ) -> None:
        self.broker_url = (broker_url_value or "").strip()
        self.queue = queue
        self.task_name = task_name
        self.source_video = source_video
        self.skip_celery = skip_celery
        self._client = None
        if not self.broker_url and not skip_celery:
            logger.warning("CelerySink: broker URL empty — triggers logged only")

    def _ensure_client(self):
        if self._client is None and self.broker_url:
            self._client = redis_client(self.broker_url, decode_responses=False)
        return self._client

    def send(self, payload: dict[str, Any]) -> str | None:
        from app.ds.debug_hits import save_hit

        if self.source_video and "source_video" not in payload:
            payload["source_video"] = remap_source_video_for_celery(self.source_video)

        save_hit(
            payload,
            source_video=None,
            force=bool(self.skip_celery or self.source_video),
        )

        task_id = str(uuid.uuid4())
        if self.skip_celery or not self.broker_url:
            logger.info(
                "DRY trigger (no celery): %s", json.dumps(payload, ensure_ascii=False)
            )
            return None

        body_json = json.dumps(
            [
                [payload],
                {},
                {"callbacks": None, "errbacks": None, "chain": None, "chord": None},
            ]
        )
        body_b64 = base64.b64encode(body_json.encode("utf-8")).decode("ascii")
        message = {
            "body": body_b64,
            "content-encoding": "utf-8",
            "content-type": "application/json",
            "headers": {
                "lang": "py",
                "task": self.task_name,
                "id": task_id,
                "shadow": None,
                "eta": None,
                "expires": None,
                "group": None,
                "group_index": None,
                "retries": 0,
                "timelimit": [None, None],
                "root_id": task_id,
                "parent_id": None,
                "argsrepr": repr([payload])[:200],
                "kwargsrepr": "{}",
                "origin": "nexus_deepstream",
                "ignore_result": True,
                "replaced_task_nesting": 0,
                "stamped_headers": None,
                "stamps": {},
            },
            "properties": {
                "correlation_id": task_id,
                "reply_to": str(uuid.uuid4()),
                "delivery_mode": 2,
                "delivery_info": {"exchange": "", "routing_key": self.queue},
                "priority": 0,
                "body_encoding": "base64",
                "delivery_tag": str(uuid.uuid4()),
            },
        }
        raw = json.dumps(message).encode("utf-8")
        client = self._ensure_client()
        assert client is not None
        client.lpush(self.queue, raw)
        logger.info(
            "Celery task queued id=%s camera=%s type=%s event=%s",
            task_id,
            payload.get("camera_id"),
            payload.get("trigger_type"),
            payload.get("event_id"),
        )
        return task_id
