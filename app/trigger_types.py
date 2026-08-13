"""Known first-line trigger types for this node."""

from __future__ import annotations

TRIGGER_TYPES: tuple[str, ...] = (
    "presence",
    "convergence",
    "vif",
    "stream_silent",
)


def normalize_enabled_triggers(value: object) -> list[str]:
    if value is None:
        return list(TRIGGER_TYPES)
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        return []
    known = set(TRIGGER_TYPES)
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        name = str(item or "").strip().lower()
        if name in known and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def camera_trigger_override(value: object) -> list[str] | None:
    """None = inherit node settings. List (possibly empty) = explicit set."""
    if value is None:
        return None
    return normalize_enabled_triggers(value)
