"""Shared helpers for Pydantic schemas."""

from __future__ import annotations


def first_str(*values: object) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def as_bool(value: object, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def normalize_email(value: str) -> str:
    email = (value or "").strip().lower()
    if len(email) > 255:
        raise ValueError("email слишком длинный")
    local, sep, domain = email.partition("@")
    if not sep or not local or not domain or " " in email:
        raise ValueError("Некорректный email")
    if "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise ValueError("Некорректный email")
    return email
