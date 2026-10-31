"""Static asset URLs with a content hash (?v=…): browsers cache the files,
and without it a deploy would keep serving the old app.css."""

from __future__ import annotations

import hashlib
from pathlib import Path

_STATIC = Path(__file__).parent / "static"
_urls: dict[str, str] = {}


def asset(name: str) -> str:
    if name not in _urls:
        digest = hashlib.md5((_STATIC / name).read_bytes()).hexdigest()[:8]
        _urls[name] = f"/static/{name}?v={digest}"
    return _urls[name]
