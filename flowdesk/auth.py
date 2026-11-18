"""Desk access key: generated on first run, stored server-side with 0600 permissions."""
from __future__ import annotations
import os
import secrets

from .config import data_dir


def desk_key() -> str:
    p = data_dir() / "desk_key.txt"
    if p.exists():
        k = p.read_text().strip()
        if k:
            return k
    k = secrets.token_urlsafe(24)
    p.write_text(k)
    os.chmod(p, 0o600)
    return k


def check_key(given: str | None) -> bool:
    return bool(given) and secrets.compare_digest(given, desk_key())
