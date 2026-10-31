"""Map regions of the loop suggestions (v0.12.0): which Geofabrik extracts the
routing container (routing/run.py) builds into its graph.

App admins add and remove them on /admin/routing. The list lives in MGC's
database (backed up) and is written to `regions.json` in the volume shared
with the container (MGC_ROUTING_DIR), which answers with `status.json`.
First start: Germany and Greater London (Michael 2026-10-30). Geofabrik's index of extracts is
fetched at most once a day - mock point `_get_index()`.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import httpx
from sqlmodel import Session, select

from .config import get_settings
from .i18n import N_
from .models import RoutingRegion

INDEX_URL = "https://download.geofabrik.de/index-v1-nogeom.json"
# Regions put on the list at the very first start. None since v1.0: an admin
# picks them on /admin/routing (Germany alone takes ~18 GB of memory to build).
# The first instance started with Germany and Greater London (2026-10-30).
FIRST: list[dict] = []
INDEX_TTL_S = 86400
SEARCH_MAX = 25
_index: tuple[float, dict[str, dict]] | None = None


class RegionError(ValueError):
    """`text` is an English key, `values` fill it."""

    def __init__(self, text: str, **values):
        super().__init__(text)
        self.text, self.values = text, values


def regions(session: Session) -> list[RoutingRegion]:
    return sorted(session.exec(select(RoutingRegion)), key=lambda r: r.name.casefold())


def _dir():
    return get_settings().routing_dir


def _write_json(name: str, data: dict) -> None:
    d = _dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / (name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(d / name)


def _read_json(name: str) -> dict:
    try:
        data = json.loads((_dir() / name).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write(session: Session, rebuild: bool = False) -> None:
    """The wish for the routing container; `rebuild` asks for a fresh build
    even with the same regions (new OSM data)."""
    token = (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if rebuild
             else str(_read_json("regions.json").get("rebuild", "")))
    _write_json("regions.json", {
        "regions": [{"id": r.geofabrik_id, "name": r.name, "pbf": r.pbf}
                    for r in regions(session)],
        "rebuild": token})


def setup(session: Session) -> None:
    """At start: FIRST the very first time, then the file follows the table
    (an admin may remove every region - it does not come back)."""
    if not (_dir() / "regions.json").exists() and not regions(session):
        for r in FIRST:
            session.add(RoutingRegion(geofabrik_id=r["id"], name=r["name"], pbf=r["pbf"]))
        session.commit()
    write(session)


def status() -> dict:
    """What the routing container reports; state "unknown" before its first word."""
    st = _read_json("status.json")
    st.setdefault("state", "unknown")
    return st


# ---------- Geofabrik's extracts ----------

async def _get_index() -> list[dict]:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        r = await client.get(INDEX_URL, headers={"User-Agent": "MyGPXContainer"})
        r.raise_for_status()
        return [f.get("properties", {}) for f in r.json().get("features", [])]


async def index() -> dict[str, dict]:
    """{id: {id, name, parent, pbf}} of every Geofabrik extract."""
    global _index
    if _index and _index[0] > time.monotonic():
        return _index[1]
    try:
        props = await _get_index()
    except (httpx.HTTPError, ValueError) as exc:
        raise RegionError(N_("Geofabrik's list of regions is not reachable right now.")) from exc
    idx = {p["id"]: {"id": p["id"], "name": p.get("name") or p["id"], "parent": p.get("parent"),
                     "pbf": (p.get("urls") or {}).get("pbf", "")}
           for p in props if p.get("id") and (p.get("urls") or {}).get("pbf")}
    _index = (time.monotonic() + INDEX_TTL_S, idx)
    return idx


def ancestors(idx: dict[str, dict], gid: str) -> list[str]:
    out, seen = [], {gid}
    parent = idx.get(gid, {}).get("parent")
    while parent and parent not in seen:
        out.append(parent)
        seen.add(parent)
        parent = idx.get(parent, {}).get("parent")
    return out


async def search(q: str, wanted: set[str]) -> list[dict]:
    """Extracts whose name or id holds every word of `q`: [{id, name, path}],
    the path being where it lies (e.g. "Europe › Germany")."""
    words = q.casefold().split()
    if not words:
        return []
    idx = await index()
    hits = [r for r in idx.values() if r["id"] not in wanted
            and all(w in f"{r['name']} {r['id']}".casefold() for w in words)]
    hits.sort(key=lambda r: (not r["name"].casefold().startswith(words[0]), len(ancestors(idx, r["id"])),
                             r["name"].casefold()))
    return [{"id": r["id"], "name": r["name"],
             "path": " › ".join(idx[a]["name"] for a in reversed(ancestors(idx, r["id"])) if a in idx)}
            for r in hits[:SEARCH_MAX]]


async def add(session: Session, gid: str, user: dict | None) -> RoutingRegion:
    """Adds an extract. One inside a region on the list is refused; regions
    inside the new one leave the list (it covers them)."""
    idx = await index()
    region = idx.get(gid)
    if region is None:
        raise RegionError(N_("Unknown region"))
    rows = regions(session)
    have = {r.geofabrik_id: r for r in rows}
    if gid in have:
        return have[gid]
    outer = [a for a in ancestors(idx, gid) if a in have]
    if outer:
        raise RegionError(N_("“{name}” is already covered by “{outer}”."),
                          name=region["name"], outer=have[outer[0]].name)
    for r in rows:
        if gid in ancestors(idx, r.geofabrik_id):
            session.delete(r)
    user = user or {}
    row = RoutingRegion(geofabrik_id=gid, name=region["name"], pbf=region["pbf"],
                        added_by_uid=user.get("uid"), added_by_username=user.get("username") or "")
    session.add(row)
    session.commit()
    write(session)
    return row


def remove(session: Session, gid: str) -> None:
    row = session.exec(select(RoutingRegion).where(RoutingRegion.geofabrik_id == gid)).first()
    if row:
        session.delete(row)
        session.commit()
    write(session)
