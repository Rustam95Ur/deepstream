"""Campus-facing public clip URLs (single builder for ingest + delivery)."""

from __future__ import annotations


def public_clip_url(event_id: str) -> str:
    """HTTP(S) URL Campus GETs for ``behaviour.video_url`` / public clips API."""
    from app.minio_store import advertised_public_base

    eid = (event_id or "").strip().removesuffix(".mp4")
    if not eid:
        return ""
    return f"{advertised_public_base()}/api/v1/public/clips/{eid}.mp4"


def refresh_video_url(
    event_id: str,
    video_url: str,
    *,
    has_clip: bool,
) -> str:
    """Prefer the current advertised public clip URL when a clip exists."""
    eid = (event_id or "").strip()
    url = (video_url or "").strip()
    if not eid or not (url or has_clip):
        return url
    return public_clip_url(eid) or url
