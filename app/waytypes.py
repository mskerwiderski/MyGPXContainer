"""Way types and surfaces of a route, like Komoot shows them (v1.2.0).

Our own GraphHopper (routing/, the same that suggests loops) matches the
track onto its road network (`POST /match`) and tells for every stretch its
`road_class` and `surface` (and `track_type`, which fills in a missing
surface). The positions never leave the server. GraphHopper's values are
grouped into a few categories (WAY, SURFACE - their order is fixed, the
colours follow it: app.css `--series-N`), each with its share of the
distance and where it lies: parts as fractions of the way, [from, to],
which the map turns into stretches of its own line.

The result is kept per file and profile (`WayInfo`): the same file always
gives the same answer, and a route turned round only reads it backwards
(`for_route`). Outside the map regions GraphHopper cannot match - that
answer is kept too and asked again after RETRY_S. Without a routing
service there is nothing to show. Mock point of the tests: `_match(body)`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta

import httpx
from sqlmodel import select

from . import gpx, routing, store
from .config import get_settings
from .db import get_session
from .i18n import N_
from .models import Route, WayInfo, now_utc
from .sports import BY_KEY

log = logging.getLogger(__name__)

MAX_POINTS = 5000          # thinned before matching; GraphHopper needs no more
RETRY_S = 86400            # an unmatched route is asked again after a day
GPS_ACCURACY_M = 40

# (key, label, GraphHopper values) - the order is the order of the bar and
# of the colours; "unknown" last, always grey
WAY = [
    ("cycleway", N_("Cycleway"), {"cycleway"}),
    ("minor", N_("Minor road"), {"residential", "unclassified", "living_street", "service",
                                 "road"}),
    ("road", N_("Road"), {"secondary", "tertiary"}),
    ("main", N_("Main road"), {"primary", "trunk", "motorway"}),
    ("track", N_("Track"), {"track"}),
    ("path", N_("Path"), {"path", "bridleway"}),
    ("footway", N_("Footway"), {"footway", "pedestrian", "steps", "platform", "corridor"}),
]
SURFACE = [
    ("asphalt", N_("Asphalt"), {"asphalt", "concrete"}),
    ("paved", N_("Paved"), {"paved"}),
    ("cobbles", N_("Cobbles"), {"paving_stones", "cobblestone", "sett", "unhewn_cobblestone"}),
    ("gravel", N_("Gravel surface"), {"compacted", "fine_gravel", "gravel", "pebblestone"}),
    ("unpaved", N_("Unpaved"), {"unpaved", "ground", "dirt", "grass", "sand", "mud", "earth",
                                "wood"}),
]
UNKNOWN = ("unknown", N_("Unknown"))
# a track without a surface tag: its grade says enough (grade1 = solid)
TRACK_GRADE = {"grade1": "paved", "grade2": "gravel", "grade3": "unpaved", "grade4": "unpaved",
               "grade5": "unpaved"}
LABELS = {k: label for k, label, _ in WAY + SURFACE} | {UNKNOWN[0]: UNKNOWN[1]}


class Unavailable(Exception):
    """`text` is an English key; `keep` = remember it (GraphHopper said no)."""

    def __init__(self, text: str, keep: bool = False):
        super().__init__(text)
        self.text, self.keep = text, keep


def available() -> bool:
    return bool(get_settings().routing_url)


def _profile(route: Route) -> str:
    on_foot = route.sports and all(BY_KEY[s].group != "bike" for s in route.sports
                                   if s in BY_KEY)
    return "foot" if on_foot else "bike"


def _category(table: list, value: str) -> str:
    for key, _, values in table:
        if value in values:
            return key
    return UNKNOWN[0]


def _cumulative(coords: list) -> list[float]:
    out = [0.0]
    for (lon0, lat0, *_), (lon1, lat1, *_) in zip(coords, coords[1:]):
        out.append(out[-1] + gpx.haversine((lat0, lon0), (lat1, lon1)))
    return out


def _summary(intervals: list[tuple[int, int, str]], cum: list[float], table: list) -> list[dict]:
    """[{key, m, share, parts: [[from, to], ...]}] in the fixed order, only
    the categories there are; neighbouring stretches of one category merged."""
    total = cum[-1] or 1.0
    by_key: dict[str, dict] = {}
    for a, z, key in intervals:
        if z <= a:
            continue
        f0, f1 = cum[a] / total, cum[z] / total
        entry = by_key.setdefault(key, {"key": key, "m": 0.0, "parts": []})
        entry["m"] += cum[z] - cum[a]
        parts = entry["parts"]
        if parts and abs(parts[-1][1] - f0) < 1e-9:
            parts[-1][1] = f1
        else:
            parts.append([f0, f1])
    order = [k for k, _, _ in table] + [UNKNOWN[0]]
    out = []
    for key in order:
        if key in by_key:
            e = by_key[key]
            out.append({"key": key, "m": round(e["m"]), "share": e["m"] / total,
                        "parts": [[round(a, 5), round(z, 5)] for a, z in e["parts"]]})
    return out


def from_match(answer: dict) -> dict:
    """GraphHopper's /match answer -> {"way": [...], "surface": [...], "m": length}."""
    path = answer["paths"][0]
    coords = path["points"]["coordinates"]
    cum = _cumulative(coords)
    details = path.get("details", {})
    way = [(a, z, _category(WAY, v)) for a, z, v in details.get("road_class", [])]
    grades = details.get("track_type", [])

    def grade_at(i: int) -> str | None:
        for a, z, v in grades:
            if a <= i < z:
                return TRACK_GRADE.get(v)
        return None

    surface = []
    for a, z, v in details.get("surface", []):
        key = _category(SURFACE, v)
        if key == UNKNOWN[0]:
            key = grade_at(a) or key
        surface.append((a, z, key))
    return {"way": _summary(way, cum, WAY), "surface": _summary(surface, cum, SURFACE),
            "m": round(cum[-1])}


async def _match(body: bytes, profile: str) -> tuple[int, dict]:
    url = get_settings().routing_url
    params = [("profile", profile), ("details", "road_class"), ("details", "surface"),
              ("details", "track_type"), ("points_encoded", "false"),
              ("instructions", "false"), ("gps_accuracy", str(GPS_ACCURACY_M))]
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(f"{url}/match", params=params, content=body,
                              headers={"Content-Type": "application/gpx+xml"})
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {}


def _cached(sha: str, profile: str) -> WayInfo | None:
    with get_session() as s:
        return s.exec(select(WayInfo).where(WayInfo.gpx_sha == sha,
                                            WayInfo.profile == profile)).first()


def _keep(sha: str, profile: str, data: dict | None, error: str) -> None:
    with get_session() as s:
        row = s.exec(select(WayInfo).where(WayInfo.gpx_sha == sha,
                                           WayInfo.profile == profile)).first()
        row = row or WayInfo(gpx_sha=sha, profile=profile)
        row.data, row.error, row.made_at = data or {}, error, now_utc()
        s.add(row)
        s.commit()


def known(route: Route) -> dict | None:
    """What is known already, without asking anyone: {"data"} or {"error"};
    None = not asked yet (or a failed answer is due again)."""
    row = _cached(route.gpx_sha, _profile(route))
    if row is None:
        return None
    made = row.made_at if row.made_at.tzinfo else row.made_at.replace(tzinfo=now_utc().tzinfo)
    if row.error and now_utc() - made > timedelta(seconds=RETRY_S):
        return None
    return {"error": row.error} if row.error else {"data": _for(route, row.data)}


def _for(route: Route, data: dict) -> dict:
    """The stored answer the way the route goes (turned round: backwards)."""
    if not route.reversed:
        return data
    flip = {kind: [{**e, "parts": [[round(1 - z, 5), round(1 - a, 5)]
                                    for a, z in reversed(e["parts"])]} for e in data[kind]]
            for kind in ("way", "surface")}
    return {**data, **flip}


async def for_route(route: Route) -> dict:
    """Way types and surfaces of the route ({"way", "surface", "m"}); asks
    GraphHopper the first time. Raises Unavailable."""
    if not available():
        raise Unavailable(N_("Way types need the routing service, which is not set up here."))
    hit = known(route)
    if hit is not None:
        if "error" in hit:
            raise Unavailable(hit["error"], keep=True)
        return hit["data"]
    profile = _profile(route)
    track = await asyncio.to_thread(lambda: gpx.parse(store.get(route.gpx_sha)))
    pts = [track.points[i] for i in gpx._thin(len(track.points), MAX_POINTS)]
    body = gpx.write("route", pts)
    started = time.monotonic()
    try:
        status, answer = await _match(body, profile)
    except httpx.HTTPError as exc:
        st = routing.status()
        if st.get("state") == "building" and not st.get("serving"):
            raise Unavailable(N_("The map is being built. Way types come in a few "
                                 "minutes.")) from exc
        raise Unavailable(N_("The routing service is not reachable right now.")) from exc
    if status != 200 or not answer.get("paths"):
        log.info("match %s %s: HTTP %s %s", route.gpx_sha[:8], profile, status,
                 str(answer.get("message", ""))[:200])
        if status >= 500:
            raise Unavailable(N_("The routing service is not reachable right now."))
        text = N_("No way types for this route: it lies (partly) outside the map regions "
                  "of this instance.")
        await asyncio.to_thread(_keep, route.gpx_sha, profile, None, text)
        raise Unavailable(text, keep=True)
    data = from_match(answer)
    log.info("match %s %s: %.1f km in %.1f s", route.gpx_sha[:8], profile,
             data["m"] / 1000, time.monotonic() - started)
    await asyncio.to_thread(_keep, route.gpx_sha, profile, data, "")
    return _for(route, data)


def label(key: str) -> str:
    return LABELS.get(key, UNKNOWN[1])

