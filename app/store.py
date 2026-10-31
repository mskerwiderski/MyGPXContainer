"""GPX files, content-addressed under DATA_DIR/store/ab/cd/<sha256>.gpx.
The uploaded bytes are kept exactly as they came."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .config import get_settings


def _path(sha: str) -> Path:
    return get_settings().data_dir / "store" / sha[:2] / sha[2:4] / f"{sha}.gpx"


def put(data: bytes) -> str:
    sha = hashlib.sha256(data).hexdigest()
    path = _path(sha)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
    return sha


def get(sha: str) -> bytes:
    return _path(sha).read_bytes()


def remove(sha: str) -> None:
    _path(sha).unlink(missing_ok=True)
