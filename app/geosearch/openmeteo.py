"""Place names from Open-Meteo's geocoding (keyless), sorted by importance:
"Roth" is Roth in Bavaria, not one of the villages in Rhineland-Palatinate.
Whatever follows a comma ("Roth, Germany", "Roth, DE", "Roth, Bavaria, Germany")
narrows by country or region. Mock point: `_get_json(params)`.
"""

from __future__ import annotations

import logging
import unicodedata
from collections import OrderedDict

import httpx

log = logging.getLogger("geosearch")

URL = "https://geocoding-api.open-meteo.com/v1/search"
CACHE_MAX = 200
_FETCH_NARROWED = 20                     # a comma filters afterwards: ask for more
_cache: OrderedDict = OrderedDict()


def clear_cache() -> None:
    _cache.clear()


async def _get_json(params: dict) -> dict:
    async with httpx.AsyncClient(timeout=6) as client:
        r = await client.get(URL, params=params)
        r.raise_for_status()
        return r.json()


def _fold(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(ch for ch in s if ch.isalnum())


def _matches(hit: dict, qualifier: str) -> bool:
    """From the start, so "Roth, Bav" finds Bavaria while typing and "Roth, AT"
    Austria, not Rhineland-Palatinate. Inside a name only from four letters on
    ("Roth, Franken" -> Mittelfranken)."""
    q = _fold(qualifier)
    if not q:
        return False
    names = [_fold(hit.get(k)) for k in
             ("country", "country_code", "admin1", "admin2", "admin3")]
    return any(n.startswith(q) or (len(q) >= 4 and q in n) for n in names)


def label(hit: dict) -> str:
    """"Roth, Bavaria, Germany" - the form `places` can narrow by again."""
    out: list[str] = []
    for part in (hit.get("name"), hit.get("admin1"), hit.get("country")):
        if part and part not in out:
            out.append(part)
    return ", ".join(out)


async def places(text: str, lang: str = "en", count: int = 10) -> list[dict]:
    """[{label, lat, lon}], most important first."""
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not parts or len(parts[0]) < 2:
        return []
    key = (text.strip().casefold(), lang, count)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    try:
        body = await _get_json({"name": parts[0], "language": lang, "format": "json",
                                "count": _FETCH_NARROWED if parts[1:] else count})
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Open-Meteo did not answer: %s", type(exc).__name__)
        return []
    hits = body.get("results") or []
    for q in parts[1:]:
        hits = [h for h in hits if _matches(h, q)]
    out = []
    for h in hits[:count]:
        try:
            out.append({"label": label(h), "lat": round(float(h["latitude"]), 6),
                        "lon": round(float(h["longitude"]), 6)})
        except (KeyError, TypeError, ValueError):
            continue
    _cache[key] = out
    if len(_cache) > CACHE_MAX:
        _cache.popitem(last=False)
    return out


async def lookup(name: str, lang: str = "en") -> tuple[str, float, float] | None:
    """(label, lat, lon) of the best match, None if there is none - never a guess."""
    hits = await places(name, lang, 1)
    return (hits[0]["label"], hits[0]["lat"], hits[0]["lon"]) if hits else None
