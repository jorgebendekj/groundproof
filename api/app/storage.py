from __future__ import annotations

import hashlib
from pathlib import Path

from .config import get_settings


def root() -> Path:
    p = Path(get_settings().storage_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


def put(rel: str, data: bytes) -> str:
    """Store bytes (local FS; S3/MinIO is the compose-time backend, see docs/DECISIONS.md)."""
    p = (root() / rel).resolve()
    if not str(p).startswith(str(root().resolve())):
        raise ValueError("path escape")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return rel


def get(rel: str) -> bytes:
    p = (root() / rel).resolve()
    if not str(p).startswith(str(root().resolve())):
        raise ValueError("path escape")
    return p.read_bytes()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
