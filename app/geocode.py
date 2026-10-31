"""Place name -> coordinates for "near …" (Open-Meteo geocoding, keyless,
sorted by importance; MFC uses the same service). Cached per process;
a network error is not cached. `_get_json` is the mock point of the tests."""

from __future__ import annotations

import httpx

URL = "https://geocoding-api.open-meteo.com/v1/search"
_cache: dict[tuple[str, str], tuple[str, float, float] | None] = {}


async def _get_json(params: dict) -> dict:
    async with httpx.AsyncClient(timeout=6) as client:
        r = await client.get(URL, params=params)
        r.raise_for_status()
        return r.json()


async def lookup(name: str, lang: str = "en") -> tuple[str, float, float] | None:
    """(label, lat, lon) of the best match, None if there is none.
    "Roth, Bayern" narrows by region or country after the comma."""
    name = name.strip()
    key = (name.casefold(), lang)
    if key in _cache:
        return _cache[key]
    head, _, hint = (p.strip() for p in name.partition(","))
    try:
        body = await _get_json({"name": head, "count": 10, "language": lang, "format": "json"})
    except (httpx.HTTPError, ValueError):
        return None
    results = body.get("results") or []
    if hint:
        h = hint.casefold()
        results = [r for r in results if any(h in (r.get(k) or "").casefold()
                                             for k in ("admin1", "admin2", "country",
                                                       "country_code"))]
    hit = None
    if results:
        r = results[0]
        label = ", ".join(x for x in (r.get("name"), r.get("admin1"), r.get("country")) if x)
        hit = (label, float(r["latitude"]), float(r["longitude"]))
    _cache[key] = hit
    return hit
