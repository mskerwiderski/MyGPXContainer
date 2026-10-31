"""Filtering and sorting the route list. Done in Python over all routes - a
family's collection is hundreds, not millions; the text search folds case
(also umlauts) and every word must match name or description."""

from __future__ import annotations

from dataclasses import dataclass, fields

from . import gpx
from .models import Route
from .sports import BY_KEY, GROUPS, PROFILES, profile

SORTS = ("new", "name", "distance", "ascent", "near")
RADII = (5, 10, 25, 50, 100, 250)


def _num(v) -> float | None:
    try:
        f = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return f if f >= 0 else None


@dataclass
class Filters:
    q: str = ""
    sport: str = ""          # "" | Garmin typeKey | "g:<group>"
    dmin: float | None = None    # km
    dmax: float | None = None
    amin: float | None = None    # m
    amax: float | None = None
    shape: str = ""          # "" | loop | oneway
    profile: str = ""        # "" | flat | hilly | mountainous
    by: str = ""             # "" | "me" (not shared with me) | username of who shared it
    folder: str = ""         # "" all | "0" the default folder | a folder id
    garmin: bool = False     # only routes in my Garmin
    place: str = ""
    lat: float | None = None     # "near me" (browser) instead of a place
    lon: float | None = None
    radius: int = 25
    sort: str = "new"
    view: str = "list"       # list | map

    @classmethod
    def parse(cls, p) -> "Filters":
        sport = p.get("sport", "")
        if sport not in BY_KEY and sport.removeprefix("g:") not in GROUPS:
            sport = ""
        radius = _num(p.get("radius"))
        sort = p.get("sort", "")
        f = cls(q=p.get("q", "").strip()[:200], sport=sport,
                dmin=_num(p.get("dmin")), dmax=_num(p.get("dmax")),
                amin=_num(p.get("amin")), amax=_num(p.get("amax")),
                shape=p.get("shape", "") if p.get("shape") in ("loop", "oneway") else "",
                profile=p.get("profile", "") if p.get("profile") in PROFILES else "",
                by=p.get("by", "").strip(), garmin=p.get("garmin") in ("1", "on", "true"),
                folder=p.get("folder", "") if p.get("folder", "").isdigit() else "",
                place=p.get("place", "").strip()[:100],
                lat=_num(p.get("lat")) if p.get("lat") not in (None, "") else None,
                lon=_num(p.get("lon")) if p.get("lon") not in (None, "") else None,
                radius=int(radius) if radius in RADII else 25,
                sort=sort if sort in SORTS else "",
                view="map" if p.get("view") == "map" else "list")
        if f.lat is not None and not -90 <= f.lat <= 90:
            f.lat = None
        if f.lon is not None and not -180 <= f.lon <= 180:
            f.lon = None
        if f.lat is None or f.lon is None:
            f.lat = f.lon = None
        if not f.sort:
            f.sort = "near" if (f.place or f.lat is not None) else "new"
        return f

    def active(self) -> int:
        """How many filters in the panel narrow the list (sort, view and the
        folder bar don't count)."""
        d = Filters()
        n = sum(1 for fl in fields(self)
                if fl.name not in ("sort", "view", "radius", "lat", "lon", "place", "folder")
                and getattr(self, fl.name) != getattr(d, fl.name))
        return n + (1 if self.place or self.lat is not None else 0)


def _matches_sport(route: Route, sport: str) -> bool:
    if not sport:
        return True
    if sport.startswith("g:"):
        g = sport[2:]
        return any(BY_KEY[k].group == g for k in route.sports if k in BY_KEY)
    return sport in route.sports


def apply(routes: list[Route], f: Filters, *, in_garmin: set[str] = frozenset(),
          center: tuple[float, float] | None = None) -> list[tuple[Route, float | None]]:
    """(route, km from the center or None), filtered and sorted."""
    words = f.q.casefold().split()
    out = []
    for r in routes:
        text = f"{r.name}\n{r.description}".casefold()
        km = r.distance_m / 1000
        if words and not all(w in text for w in words):
            continue
        if not _matches_sport(r, f.sport):
            continue
        if (f.dmin is not None and km < f.dmin) or (f.dmax is not None and km > f.dmax):
            continue
        asc = r.ascent_m
        if f.amin is not None and (asc is None or asc < f.amin):
            continue
        if f.amax is not None and (asc is None or asc > f.amax):
            continue
        if (f.shape == "loop" and not r.loop) or (f.shape == "oneway" and r.loop):
            continue
        if f.profile and profile(r.distance_m, r.ascent_m, r.sports) != f.profile:
            continue
        if f.folder and (r.folder_id or 0) != int(f.folder):
            continue
        if f.by == "me" and r.shared_from:
            continue
        if f.by not in ("", "me") and r.shared_by_username != f.by:
            continue
        if f.garmin and r.uid not in in_garmin:
            continue
        away = None
        if center:
            away = gpx.haversine(center, (r.start_lat, r.start_lon)) / 1000
            if away > f.radius:
                continue
        out.append((r, away))
    sort = "new" if f.sort == "near" and not center else f.sort
    key = {"name": lambda x: x[0].name.casefold(),
           "distance": lambda x: x[0].distance_m,
           "ascent": lambda x: x[0].ascent_m or 0,
           "near": lambda x: x[1],
           "new": lambda x: x[0].created_at}[sort]
    return sorted(out, key=key, reverse=sort == "new")
