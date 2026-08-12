"""Assemble sinks from NodeSettings."""

from __future__ import annotations

from typing import Any

from app.ds.sinks import CompositeSink, LogSink
from app.ds.sinks.celery_sink import CelerySink
from app.ds.sinks.http_sink import HttpSink
from app.settings import NodeSettings


def build_sink(
    settings: NodeSettings,
    *,
    source_video: str | None = None,
    max_triggers: int | None = None,
) -> CompositeSink:
    sinks: list[Any] = []
    if settings.enable_log_sink:
        sinks.append(LogSink(source_video=source_video))
    if settings.enable_http_sink and settings.triggers_url.strip():
        sinks.append(
            HttpSink(
                settings.triggers_url,
                timeout_sec=settings.triggers_timeout_sec,
                token=settings.api_token,
                source_video=source_video,
            )
        )
    if settings.enable_celery_sink and settings.celery_broker_url.strip():
        sinks.append(
            CelerySink(
                settings.celery_broker_url,
                queue=settings.celery_queue,
                task_name=settings.celery_task_name,
                source_video=source_video,
            )
        )
    if not sinks:
        sinks.append(LogSink(source_video=source_video))
    return CompositeSink(
        sinks, source_video=source_video, max_triggers=max_triggers
    )
