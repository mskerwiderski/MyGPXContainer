"""Place names: for naming suggested routes, and the address search of /suggest.

Naming follows Michael's scheme of 2026-10-27 ("Starnberg via Percha 42k
380hm", "München to Schliersee 118k 1240hm") and uses the routing
container's `places.json` - the OSM place nodes (city, town, village, suburb)
of the map regions. Local on purpose: the start of a route is mostly the
front door, it never leaves this server.

The address search while typing asks Photon (OSM, made for search-as-you-type;
MGC_PHOTON_URL, photon.komoot.io), from the server: the typed text goes out,
the bias towards the user's area only rounded to ~10 km. That part is the
MyCommons block `geosearch` (copy in app/geosearch/, never edit it). Mock
points: `geosearch.photon._get_json(params)` and the places file.
"""

from __future__ import annotations

import json
import math

from . import gpx
from .config import get_settings
from .geosearch import photon

WEIGHT = {"city": 4.0, "town": 2.0, "village": 1.0}     # a city wins from further away
LOCALITY_KM = 25
SUBURB_KM = 4
CELL = 0.1                                              # degrees of the lookup grid
_grid: tuple[float, dict] | None = None                 # (mtime of places.json, grid)


def _places_grid() -> dict:
    """{(lat cell, lon cell): [[lat, lon, kind, name], …]} from places.json, read
    again when the routing container wrote a new one."""
    global _grid
    path = get_settings().routing_dir / "places.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    if _grid and _grid[0] == mtime:
        return _grid[1]
    try:
        places = json.loads(path.read_text()).get("places", [])
    except (OSError, ValueError):
        return {}
    grid: dict = {}
    for p in places:
        grid.setdefault((math.floor(p[0] / CELL), math.floor(p[1] / CELL)), []).append(p)
    _grid = (mtime, grid)
    return grid


def _near(lat: float, lon: float, kinds, max_km: float) -> list[tuple[float, list]]:
    grid = _places_grid()
    reach = math.ceil(max_km / (111 * CELL * max(math.cos(math.radians(lat)), 0.2))) + 1
    ci, cj = math.floor(lat / CELL), math.floor(lon / CELL)
    out = []
    for i in range(ci - reach, ci + reach + 1):
        for j in range(cj - reach, cj + reach + 1):
            for p in grid.get((i, j), ()):
                if p[2] in kinds:
                    km = gpx.haversine((lat, lon), (p[0], p[1])) / 1000
                    if km <= max_km:
                        out.append((km, p))
    return out


def _locality(lat: float, lon: float) -> list | None:
    found = _near(lat, lon, WEIGHT, LOCALITY_KM)
    return min(found, key=lambda x: x[0] / WEIGHT[x[1][2]])[1] if found else None


def locality(lat: float, lon: float) -> str | None:
    """The city, town or village a point belongs to: the nearest, a city
    counting four times, a town twice as far as a village."""
    place = _locality(lat, lon)
    return place[3] if place else None


def suburb(lat: float, lon: float) -> str | None:
    found = _near(lat, lon, ("suburb",), SUBURB_KM)
    return min(found, key=lambda x: x[0])[1][3] if found else None


def _other(lat: float, lon: float, start: str) -> str | None:
    """The place of a point - its suburb when it lies in the start's own town
    (a run through Munich: "München via Schwabing")."""
    name = locality(lat, lon)
    if name == start:
        name = suburb(lat, lon)
    return name if name and name != start else None


def route_head(points: list, oneway: bool, stops: list | None = None) -> str | None:
    """"Starnberg via Percha" for a loop (via: where it gets farthest from the
    start), "München to Schliersee" from A to B; with stops they are the via
    ("Starnberg via Percha, Andechs", "München to Schliersee via Holzkirchen").
    None without a place list."""
    start = locality(points[0][0], points[0][1])
    if not start:
        return None
    end = _other(points[-1][0], points[-1][1], start) if oneway else None
    if stops:
        names = [n for n in dict.fromkeys(_other(s[0], s[1], start) for s in stops)
                 if n and n != end]
        head = f"{start} to {end}" if end else start
        return f"{head} via {', '.join(names)}" if names else head
    if oneway:
        return f"{start} to {end}" if end else start
    far = max(points, key=lambda p: gpx.haversine(points[0], p))
    via = _other(far[0], far[1], start)
    return f"{start} via {via}" if via else start


def label_at(lat: float, lon: float) -> str:
    """A name for a point tapped on the map: in a city its suburb with it
    ("Altstadt, München"), else the town or village alone - suburbs and
    places are found apart, and outside cities a suburb near by often
    belongs to the next town ("Puchheim-Ort" near Alling); else the
    coordinates."""
    place = _locality(lat, lon)
    if not place:
        return f"{lat:.5f}, {lon:.5f}"
    if place[2] == "city":
        part = suburb(lat, lon)
        if part and part != place[3]:
            return f"{part}, {place[3]}"
    return place[3]


# ---------- address search: the MyCommons block geosearch ----------

photon.configure(user_agent="MyGPXContainer", url=lambda: get_settings().photon_url)
search = photon.search
