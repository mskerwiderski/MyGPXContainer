"""Addresses and places while typing, from Photon (OpenStreetMap, keyless).

The typed text goes out to the service, the bias only rounded to ~10 km. Mock
point: `_get_json(params)`.
"""

from __future__ import annotations

import logging
from collections import OrderedDict

import httpx

log = logging.getLogger("geosearch")

CACHE_MAX = 200
# Areas, not places one can start from: "Roth" would be the middle of the county.
_NOT_A_PLACE = {"county", "state", "country"}
_url = "https://photon.komoot.io"
_user_agent = "geosearch"                # photon.komoot.io refuses httpx's default with 403
_cache: OrderedDict = OrderedDict()


def configure(*, user_agent: str | None = None, url=None) -> None:
    """The app's name towards the service, and its own Photon if it runs one:
    a string or a callable, for settings that are read when needed."""
    global _url, _user_agent
    if user_agent:
        _user_agent = user_agent
    if url:
        _url = url


def clear_cache() -> None:
    _cache.clear()


async def _get_json(params: dict) -> dict:
    async with httpx.AsyncClient(timeout=8) as client:
        base = _url() if callable(_url) else _url
        r = await client.get(base.rstrip("/") + "/api/", params=params,
                             headers={"User-Agent": _user_agent})
        r.raise_for_status()
        return r.json()


def label(p: dict) -> str:
    """"Bahnhofstraße 5, 82319 Starnberg", "Lenggries, Bayern", "London, Vereinigtes Königreich"."""
    street, number = p.get("street"), p.get("housenumber")
    first = f"{street} {number}" if street and number else (p.get("name") or street or "")
    city = p.get("city")
    where = " ".join(x for x in (p.get("postcode"), city) if x) if city and city != first else ""
    tail = p.get("country") if p.get("countrycode") not in (None, "DE") else (
        "" if where else p.get("state") or "")
    return ", ".join(x for x in (first, where, tail) if x)


async def search(q: str, lang: str = "en", near: tuple[float, float] | None = None) -> list[dict]:
    """[{label, lat, lon}] for what the user typed, nearby first. Empty when
    Photon does not answer - the form then works with the plain text."""
    q = " ".join(q.split())[:100]
    if len(q) < 3:
        return []
    bias = (round(near[0], 1), round(near[1], 1)) if near else None
    key = (q.casefold(), lang, bias)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    params = {"q": q, "limit": 6, "lang": lang if lang in ("de", "en", "fr") else "default"}
    if bias:
        params.update(lat=bias[0], lon=bias[1])
    try:
        data = await _get_json(params)
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Photon did not answer: %s", type(exc).__name__)
        return []
    out, seen = [], set()
    for f in data.get("features", []):
        props = f.get("properties") or {}
        coords = (f.get("geometry") or {}).get("coordinates") or []
        text = label(props)
        if props.get("type") not in _NOT_A_PLACE and len(coords) >= 2 and text and text not in seen:
            seen.add(text)
            out.append({"label": text, "lat": round(coords[1], 6), "lon": round(coords[0], 6)})
    _cache[key] = out
    if len(_cache) > CACHE_MAX:
        _cache.popitem(last=False)
    return out
