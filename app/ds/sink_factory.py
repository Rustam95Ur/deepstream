"""Assemble log + webhook-queue sinks from NodeSettings."""

from __future__ import annotations

from typing import Any

from app.ds.config import CameraConfig
from app.ds.sinks import CompositeSink, LogSink
from app.ds.sinks.async_sink import AsyncSink
from app.ds.sinks.clip_sink import IncidentClipSink
from app.ds.sinks.outbound_sink import OutboundEnqueueSink
from app.settings import NodeSettings


def build_sink(
    settings: NodeSettings,
    *,
    cameras: list[CameraConfig] | None = None,
    source_video: str | None = None,
    max_triggers: int | None = None,
) -> AsyncSink:
    sinks: list[Any] = []
    if settings.enable_log_sink:
        sinks.append(LogSink(source_video=source_video))
    if settings.enable_http_sink:
        sinks.append(OutboundEnqueueSink(source_video=source_video))
    if not sinks:
        sinks.append(LogSink(source_video=source_video))
    composite = CompositeSink(
        sinks, source_video=source_video, max_triggers=max_triggers
    )
    clip = IncidentClipSink(
        composite,
        cameras or [],
        enabled=settings.enable_clip_record,
    )
    return AsyncSink(clip)
