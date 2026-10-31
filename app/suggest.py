"""Route suggestions (v0.12.0, Michael 2026-10-30): three round trips from a
start point for a sport, a distance and a profile - or, since v0.14.0, three
ways from A to B - from MGC's own GraphHopper (`routing/`, MGC_ROUTING_URL -
positions never leave this server).

From A to B: GraphHopper's own alternatives come close to each other, so
four more go over a point beside the middle (left and right, at 15 and 30 %
of the distance); scored like the loops, but on the length beyond the
shortest instead of a wished distance. Every candidate has a key ("h30",
"a1", "v2"), so "take over" computes that one again.

Twelve candidates, one per 30° heading, are asked in parallel
(`algorithm=round_trip`; the seed barely changes a loop, the heading does).
Each request carries a custom model: the profile wish plus rules for the
sport. Every candidate gets km and climb as every route does (`gpx.stats`),
its profile with the sport's limits, and how much of it runs twice, is
unpaved or on big roads; the score weighs that, and the best three going
different ways are kept. The rules and weights come from the trial run of
2026-10-30 (docs/plan.md). Mock point of the tests: `_route(body)`.
"""

from __future__ import annotations

import asyncio
import logging
import math
import weakref
from dataclasses import dataclass

import httpx

from . import gpx, sports
from .config import get_settings
from .i18n import N_

# MGC sport -> GraphHopper profile (routing/config.yml); sports not here
# are not offered
ENGINE = {
    "road_biking": "racingbike",
    "gravel_cycling": "gravel", "cyclocross": "gravel",
    "mountain_biking": "mtb", "e_bike_mountain": "mtb",
    "cycling": "bike", "e_bike_fitness": "bike",
    "running": "foot", "street_running": "foot",
    "trail_running": "hike", "hiking": "hike",
    "walking": "foot", "casual_walking": "foot", "speed_walking": "foot",
}
OFFERED = [s for s in sports.SPORTS if s.key in ENGINE]
HEADINGS = range(0, 360, 30)
MIN_KM = 2
# the longest route, loop or A to B (Michael 2026-10-30): by bike 300 km, on foot 100
LIMIT_KM = {"bike": 300, "run": 100, "walk": 100}
ASK_SPAN = 1.5          # a corrected request may ask up to 1.5 × the limit
CORRECT_OFF = 0.08      # loops off by more than this get a second, corrected round
CHIPS = {"bike": (30, 50, 80, 100), "run": (5, 10, 15, 21), "walk": (5, 10, 15, 20)}

_BIG = "road_class == PRIMARY || road_class == TRUNK || road_class == SECONDARY"
_UNPAVED = ("surface == GRAVEL || surface == COMPACTED || surface == FINE_GRAVEL || "
            "surface == DIRT || surface == GROUND || surface == UNPAVED")
WISH = {
    "flat": [{"if": "average_slope >= 6 || average_slope <= -6", "multiply_by": "0.3"},
             {"else_if": "average_slope >= 3 || average_slope <= -3", "multiply_by": "0.7"}],
    "hilly": [{"if": "average_slope < 2 && average_slope > -2", "multiply_by": "0.7"}],
    "mountainous": [{"if": "average_slope < 3 && average_slope > -3", "multiply_by": "0.4"}],
}
RULES = {
    "gravel": [{"if": _BIG, "multiply_by": "0.2"},
               {"else_if": "road_class == TERTIARY || road_class == RESIDENTIAL",
                "multiply_by": "0.6"},
               {"if": _UNPAVED + " || road_class == TRACK", "multiply_by": "1.5"}],
    "mtb": [{"if": _BIG, "multiply_by": "0.2"},
            {"else_if": "road_class == TERTIARY || road_class == RESIDENTIAL",
             "multiply_by": "0.6"}],
    "hike": [{"if": _BIG + " || road_class == TERTIARY", "multiply_by": "0.2"},
             {"else_if": "road_class == RESIDENTIAL", "multiply_by": "0.6"}],
    "foot": [{"if": _BIG + " || road_class == TERTIARY", "multiply_by": "0.3"},
             {"if": "road_class == TRACK || road_class == PATH || road_class == FOOTWAY",
              "multiply_by": "1.3"}],
    "racingbike": [{"if": "road_class == PRIMARY || road_class == TRUNK", "multiply_by": "0.3"}],
    "bike": [{"if": _BIG, "multiply_by": "0.4"}],
}
UNPAVED = {"gravel", "compacted", "fine_gravel", "dirt", "ground", "unpaved", "grass", "sand"}
ORDER = {"flat": 0, "hilly": 1, "mountainous": 2}
PARALLEL = 6                 # requests at once - twelve strained a fresh server
log = logging.getLogger(__name__)
_gates: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()   # one per event loop


class Unavailable(Exception):
    """`text` is an English key, `values` fill it."""

    def __init__(self, text: str, **values):
        super().__init__(text)
        self.text, self.values = text, values


def limit(sport: str) -> int:
    """The longest route for the sport, in km."""
    return LIMIT_KM[sports.BY_KEY[sport].group]


@dataclass
class Loop:
    """A suggested route: a loop or one from A to B."""
    heading: int
    points: list            # (lat, lon, ele)
    distance_m: float
    ascent_m: int | None
    profile: str | None
    repeat: float           # share of the length run twice (out and back)
    unpaved: int            # % of the length
    big_roads: int          # % on primary/secondary/trunk roads
    score: float = 0.0
    bearing: float = 0.0    # start -> middle of the loop
    key: str = ""           # which candidate: "h<heading>" | "a<n>" | "v<n>"
    asked_km: float = 0.0   # the distance asked from GraphHopper (a loop, maybe corrected)

    @property
    def km(self) -> float:
        return self.distance_m / 1000


async def _route(body: dict) -> tuple[int, dict]:
    """(status, JSON) of GraphHopper's POST /route, at most PARALLEL at once."""
    url = get_settings().routing_url
    if not url:
        raise Unavailable(N_("Suggestions are not set up here."))
    loop = asyncio.get_running_loop()
    gate = _gates.get(loop) or _gates.setdefault(loop, asyncio.Semaphore(PARALLEL))
    try:
        async with gate, httpx.AsyncClient(timeout=40) as client:
            r = await client.post(f"{url}/route", json=body)
    except httpx.HTTPError as exc:
        raise Unavailable(N_("Suggestions are not available right now. Please try again "
                             "in a minute.")) from exc
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {}


def body(sport: str, start: tuple[float, float], km: float, wish: str, heading: int) -> dict:
    engine = ENGINE[sport]
    return {"profile": engine, "points": [[start[1], start[0]]], "algorithm": "round_trip",
            "round_trip.distance": round(km * 1000), "round_trip.seed": 0, "headings": [heading],
            "ch.disable": True, "elevation": True, "points_encoded": False,
            "instructions": False, "details": ["surface", "road_class"],
            "custom_model": {"priority": WISH[wish] + RULES.get(engine, [])}}


def _shares(path: dict, points: list, name: str) -> dict[str, float]:
    """% of the length per value of a GraphHopper path detail."""
    out: dict[str, float] = {}
    for a, z, value in path.get("details", {}).get(name, []):
        d = sum(gpx.haversine(points[i], points[i + 1]) for i in range(a, min(z, len(points) - 1)))
        key = str(value).lower()
        out[key] = out.get(key, 0) + d
    total = sum(out.values()) or 1
    return {k: v / total * 100 for k, v in out.items()}


def _cells(points: list, size: float = 0.0003) -> list[tuple[int, int]]:
    """A ~30 m grid: where a loop runs."""
    return [(round(p[0] / size), round(p[1] / size * math.cos(math.radians(p[0]))))
            for p in points]


def repeat_share(points: list) -> float:
    """Share of the length on ground already passed further back (out and
    back on the same way; neighbours on the grid don't count)."""
    seen: dict = {}
    rep = total = 0.0
    cells = _cells(points)
    for i in range(1, len(points)):
        d = gpx.haversine(points[i - 1], points[i])
        total += d
        j = seen.get(cells[i])
        if j is not None and i - j > 15:
            rep += d
        seen.setdefault(cells[i], i)
    return rep / total if total else 0.0


def _bearing(start: tuple[float, float], points: list) -> float:
    lat = sum(p[0] for p in points) / len(points)
    lon = sum(p[1] for p in points) / len(points)
    return math.degrees(math.atan2((lon - start[1]) * math.cos(math.radians(start[0])),
                                   lat - start[0])) % 360


def score(loop: Loop, sport: str, km: float, wish: str) -> float:
    return round(abs(loop.km - km) / km * 2 + _ground(loop, sport, wish), 3)


def score_oneway(route: Loop, sport: str, shortest_km: float, wish: str) -> float:
    return round((route.km / shortest_km - 1) * 1.5 + _ground(route, sport, wish), 3)


def _ground(loop: Loop, sport: str, wish: str) -> float:
    """What every suggestion is judged on: run twice, profile, roads, surface."""
    s = loop.repeat * 1.5 + abs(ORDER.get(loop.profile or "flat", 0) - ORDER[wish])
    engine = ENGINE[sport]
    if engine in ("gravel", "mtb", "hike", "foot"):
        s += loop.big_roads / 100 * 2
    if engine == "gravel":
        s -= loop.unpaved / 100              # the more gravel the better
    if engine == "racingbike":
        s += loop.unpaved / 100 * 3
    return s


def _no_map(answer: dict) -> bool:
    return "cannot find point" in str(answer.get("message", "")).lower()


def _paths(status: int, answer: dict) -> list[dict]:
    """GraphHopper's paths; [] when it found none this way. Raises Unavailable
    when it cannot answer at all, or a point lies outside the map."""
    if status == 200 and answer.get("paths"):
        return answer["paths"]
    if _no_map(answer):
        raise Unavailable(N_("There is no map for this area yet. An app admin can add it."))
    if status >= 500 or status == 404:
        raise Unavailable(N_("Suggestions are not available right now. Please try again "
                             "in a minute."))
    return []


def _make(path: dict, sport: str, key: str, start: tuple[float, float]) -> Loop | None:
    points = [(c[1], c[0], c[2] if len(c) > 2 else None) for c in path["points"]["coordinates"]]
    if len(points) < 2:
        return None
    st = gpx.stats(gpx.Track(points=points))
    surface, road = _shares(path, points, "surface"), _shares(path, points, "road_class")
    return Loop(heading=int(key[1:]) if key.startswith("h") else 0, key=key, points=points,
                distance_m=st["distance_m"], ascent_m=st["ascent_m"],
                profile=sports.profile(st["distance_m"], st["ascent_m"], [sport]),
                repeat=repeat_share(points),
                unpaved=round(sum(v for k, v in surface.items() if k in UNPAVED)),
                big_roads=round(sum(road.get(k, 0) for k in ("primary", "secondary", "trunk"))),
                bearing=_bearing(start, points))


async def one(sport: str, start: tuple[float, float], km: float, wish: str,
              heading: int, target: float | None = None) -> Loop | None:
    """One loop, asking GraphHopper for `km`, scored against `target` (the
    wished distance, default `km`); None if it finds none this way. Raises
    Unavailable."""
    paths = _paths(*await _route(body(sport, start, km, wish, heading)))
    loop = _make(paths[0], sport, f"h{heading}", start) if paths else None
    if loop:
        loop.asked_km = km
        loop.score = score(loop, sport, target or km, wish)
    return loop


def pick(loops: list[Loop], n: int = 3, apart: bool = True, shared: float = 0.4) -> list[Loop]:
    """The best n that go different ways: each next one (with `apart`) at
    least 60° from those chosen and sharing less than `shared` of its ground
    with them."""
    chosen: list[tuple[Loop, set]] = []
    for loop in sorted(loops, key=lambda x: x.score):
        cells = set(_cells(loop.points))
        if all((not apart or min(abs(loop.bearing - c.bearing), 360 - abs(loop.bearing - c.bearing)) >= 60)
               and len(cells & cc) / len(cells | cc) < shared for c, cc in chosen):
            chosen.append((loop, cells))
        if len(chosen) == n:
            break
    return [c for c, _ in chosen]


# ---------- from A to B ----------

VIA_SHIFTS = (-0.3, -0.15, 0.15, 0.3)     # beside the middle, share of the distance A-B
ONEWAY_KEYS = ("a0", "a1", "a2") + tuple(f"v{i}" for i in range(len(VIA_SHIFTS)))
MIN_ONEWAY_KM = 1                          # as the crow flies


def via(start: tuple[float, float], finish: tuple[float, float], shift: float) -> tuple[float, float]:
    """A point beside the middle of A-B, `shift` × the distance to the left (-)
    or right (+) of the way."""
    k_lat = 111_320
    k_lon = 111_320 * math.cos(math.radians((start[0] + finish[0]) / 2))
    dx, dy = (finish[1] - start[1]) * k_lon, (finish[0] - start[0]) * k_lat
    x, y = dx / 2 + dy * shift, dy / 2 - dx * shift
    return start[0] + y / k_lat, start[1] + x / k_lon


def oneway_body(sport: str, start: tuple[float, float], finish: tuple[float, float],
                wish: str, group: str) -> dict:
    """group "a": GraphHopper's alternatives; "v<n>": over the n-th point beside."""
    engine = ENGINE[sport]
    b = {"profile": engine, "ch.disable": True, "elevation": True, "points_encoded": False,
         "instructions": False, "details": ["surface", "road_class"],
         "custom_model": {"priority": WISH[wish] + RULES.get(engine, [])}}
    if group == "a":
        b.update({"points": [[start[1], start[0]], [finish[1], finish[0]]],
                  "algorithm": "alternative_route", "alternative_route.max_paths": 3,
                  "alternative_route.max_weight_factor": 2.0,
                  "alternative_route.max_share_factor": 0.8})
    else:
        v = via(start, finish, VIA_SHIFTS[int(group[1:])])
        b["points"] = [[start[1], start[0]], [v[1], v[0]], [finish[1], finish[0]]]
    return b


async def _oneway_group(sport: str, start, finish, wish: str, group: str) -> list[Loop]:
    paths = _paths(*await _route(oneway_body(sport, start, finish, wish, group)))
    keys = [f"a{i}" for i in range(len(paths))] if group == "a" else [group]
    return [r for r in (_make(p, sport, k, start) for p, k in zip(paths, keys)) if r]


async def oneway(sport: str, start: tuple[float, float], finish: tuple[float, float],
                 wish: str) -> list[Loop]:
    """Up to three ways from A to B, best first. Raises Unavailable."""
    groups = ["a"] + [f"v{i}" for i in range(len(VIA_SHIFTS))]
    found = await asyncio.gather(*(_oneway_group(sport, start, finish, wish, g) for g in groups),
                                 return_exceptions=True)
    routes = [r for f in found if isinstance(f, list) for r in f]
    if not routes:
        _raise_first(found)
        return []
    longest = limit(sport)
    if not [r for r in routes if r.km <= longest]:
        raise Unavailable(N_("Every way from the start to the destination is longer than "
                             "{max} km."), max=longest)
    routes = [r for r in routes if r.km <= longest]
    shortest = min(r.km for r in routes)
    for r in routes:
        r.score = score_oneway(r, sport, shortest, wish)
    return pick(routes, apart=False, shared=0.6)


async def oneway_one(sport: str, start: tuple[float, float], finish: tuple[float, float],
                     wish: str, key: str) -> Loop | None:
    """The candidate `key` again (for "take over")."""
    group = "a" if key.startswith("a") else key
    return next((r for r in await _oneway_group(sport, start, finish, wish, group)
                 if r.key == key), None)


def _raise_first(found: list) -> None:
    """Say why nothing came back: the clearest reason first."""
    for kind in (Unavailable, BaseException):
        for f in found:
            if isinstance(f, kind):
                raise f


async def _round(sport: str, start, ask: float, km: float, wish: str) -> list[Loop]:
    found = await asyncio.gather(*(one(sport, start, ask, wish, h, km) for h in HEADINGS),
                                 return_exceptions=True)
    loops = [f for f in found if isinstance(f, Loop)]
    failed = [f for f in found if isinstance(f, BaseException)]
    if failed:
        log.warning("suggest %s %s km %s: %d of %d candidates failed (%s, cause %r)", sport, ask,
                    wish, len(failed), len(found), failed[0], failed[0].__cause__)
    if not loops:
        _raise_first(found)
    return loops


async def suggest(sport: str, start: tuple[float, float], km: float, wish: str) -> list[Loop]:
    """Up to three loops of about `km`, best first. GraphHopper's loops grow
    too long on long distances (300 km asked: 360-370 km, 2026-10-30): when
    they are off by more than CORRECT_OFF, a second round asks for the
    distance corrected by how far off they were. Raises Unavailable."""
    loops = await _round(sport, start, km, km, wish)
    if loops:
        ratios = sorted(loop.km / km for loop in loops)
        ratio = ratios[len(ratios) // 2]
        ask = min(max(km / ratio, MIN_KM), limit(sport) * ASK_SPAN)
        if abs(ratio - 1) > CORRECT_OFF and abs(ask - km) >= 0.5:
            loops += await _round(sport, start, ask, km, wish)
    return pick(loops)


def fits(loops: list[Loop], wish: str) -> bool:
    """Do the loops have the wished profile? Otherwise the terrain does not give it."""
    return any(loop.profile == wish for loop in loops)
