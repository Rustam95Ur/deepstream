"""PBKDF2 password hashes (stdlib, no extra deps)."""

from __future__ import annotations

import hashlib
import hmac
import secrets

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 210_000
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    salt = secrets.token_hex(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        _ITERATIONS,
    ).hex()
    return f"{_ALGO}${_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters_s, salt, digest = stored.split("$", 3)
        iterations = int(iters_s)
    except (ValueError, AttributeError):
        return False
    if algo != _ALGO or iterations < 1 or not salt or not digest:
        return False
    check = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return hmac.compare_digest(check, digest)
