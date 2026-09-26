"""
Incident ring-buffer: gst-launch + splitmuxsink, same as Campus ``rtsp_writer``.

Stable facade — implementation lives in ring_config / ring_worker / ring_supervisor.
"""

from __future__ import annotations

from app.ds.ring_config import (
    GST_LAUNCH,
    CameraSpec,
    camera_segment_dir,
    clips_root,
    edge_margin_s,
    gst_launch_available,
    keep_buffer_s,
    load_rtsp_cameras,
    safe_camera_dirname,
    segment_dur_sec,
    segment_root,
)
from app.ds.ring_supervisor import (
    IncidentRingBufferSupervisor,
    RingBufferManager,
    get_ring_buffer,
)
from app.ds.ring_worker import IncidentRingBufferWorker, gc_old_segments

__all__ = [
    "GST_LAUNCH",
    "CameraSpec",
    "IncidentRingBufferSupervisor",
    "IncidentRingBufferWorker",
    "RingBufferManager",
    "camera_segment_dir",
    "clips_root",
    "edge_margin_s",
    "gc_old_segments",
    "get_ring_buffer",
    "gst_launch_available",
    "keep_buffer_s",
    "load_rtsp_cameras",
    "safe_camera_dirname",
    "segment_dur_sec",
    "segment_root",
]
