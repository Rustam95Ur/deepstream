"""Per-trigger-type threshold profiles (node settings)."""

from __future__ import annotations

from typing import Any

THRESHOLD_TRIGGER_TYPES: tuple[str, ...] = (
    "presence",
    "convergence",
    "vif",
    "stream_silent",
)


def flat_threshold_defaults(settings: Any) -> dict[str, dict[str, Any]]:
    """Build per-type maps from legacy flat NodeSettings fields."""
    return {
        "presence": {
            "presence_min_people": int(
                getattr(settings, "presence_min_people", 1) or 1
            ),
            "presence_sustain_s": float(
                getattr(settings, "presence_sustain_s", 2.0) or 2.0
            ),
            "cooldown_s": float(getattr(settings, "cooldown_s", 30.0) or 30.0),
        },
        "convergence": {
            "min_tracks": int(getattr(settings, "min_tracks", 2) or 2),
            "converge_dist_bh": float(
                getattr(settings, "converge_dist_bh", 1.5) or 1.5
            ),
            "speed_thresh_bh": float(getattr(settings, "speed_thresh_bh", 2.0) or 2.0),
            "sustain_s": float(getattr(settings, "sustain_s", 0.4) or 0.4),
            "cooldown_s": float(getattr(settings, "cooldown_s", 30.0) or 30.0),
        },
        "vif": {
            "vif_iou_thresh": float(getattr(settings, "vif_iou_thresh", 0.25) or 0.25),
            "vif_sustain_s": float(getattr(settings, "vif_sustain_s", 0.3) or 0.3),
            "cooldown_s": float(getattr(settings, "cooldown_s", 30.0) or 30.0),
        },
        "stream_silent": {
            "stream_silent_s": float(
                getattr(settings, "stream_silent_s", 30.0) or 30.0
            ),
            "cooldown_s": float(getattr(settings, "cooldown_s", 30.0) or 30.0),
        },
    }


def merge_trigger_thresholds(
    settings: Any,
    raw: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Defaults from flat fields, overridden by trigger_thresholds."""
    base = flat_threshold_defaults(settings)
    overrides = (
        raw if isinstance(raw, dict) else getattr(settings, "trigger_thresholds", None)
    )
    if not isinstance(overrides, dict):
        return base
    out: dict[str, dict[str, Any]] = {}
    for kind in THRESHOLD_TRIGGER_TYPES:
        merged = dict(base.get(kind) or {})
        patch = overrides.get(kind)
        if isinstance(patch, dict):
            for key, value in patch.items():
                if value is not None and value != "":
                    merged[key] = value
        out[kind] = merged
    return out


def sync_flat_from_profiles(settings: Any) -> None:
    """Keep legacy flat fields aligned with per-type profiles (for API compat)."""
    profiles = merge_trigger_thresholds(settings)
    presence = profiles.get("presence") or {}
    convergence = profiles.get("convergence") or {}
    vif = profiles.get("vif") or {}
    silent = profiles.get("stream_silent") or {}
    if "presence_min_people" in presence:
        settings.presence_min_people = int(presence["presence_min_people"])
    if "presence_sustain_s" in presence:
        settings.presence_sustain_s = float(presence["presence_sustain_s"])
    if "min_tracks" in convergence:
        settings.min_tracks = int(convergence["min_tracks"])
    if "converge_dist_bh" in convergence:
        settings.converge_dist_bh = float(convergence["converge_dist_bh"])
    if "speed_thresh_bh" in convergence:
        settings.speed_thresh_bh = float(convergence["speed_thresh_bh"])
    if "sustain_s" in convergence:
        settings.sustain_s = float(convergence["sustain_s"])
    if "vif_iou_thresh" in vif:
        settings.vif_iou_thresh = float(vif["vif_iou_thresh"])
    if "vif_sustain_s" in vif:
        settings.vif_sustain_s = float(vif["vif_sustain_s"])
    if "stream_silent_s" in silent:
        settings.stream_silent_s = float(silent["stream_silent_s"])
    # Global cooldown_s = max per-type (legacy field used as fallback only).
    cooldowns = [
        float(p.get("cooldown_s") or 0)
        for p in profiles.values()
        if isinstance(p, dict) and p.get("cooldown_s") is not None
    ]
    if cooldowns:
        settings.cooldown_s = max(cooldowns)
