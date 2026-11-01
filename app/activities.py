"""Garmin activities as routes (v1.4.0, Michael 2026-11-01).

Always the SIGNED-IN user's Garmin (`auth.garmin_token`): their own
activities, and someone else's only when it is public. Two ways in: a link
to an activity (sources/garmin.py) and the page "From Garmin" (`page`), a
list of the user's activities with GPS, filtered by sport and dates,
several taken at once; a multisport activity offers its parts one by one.

Only the way is taken: Garmin's GPX export, its points with elevation -
no times, no heart rate (a route is a plan, and a copy shared must carry
nothing personal). Standing still leaves a knot of GPS points, a recording
every second far more points than a route needs: a point closer than
MIN_SPACING_M to the last one kept goes (`clean`). The name follows the
scheme of the suggestions ("Starnberg via Percha 42k 380hm"), the activity's
own name and date go into the description. Source "garmin_activity",
external id the activity id: the same activity twice is a duplicate.
Mock point of the tests: `garmin_courses._client`.
"""

from __future__ import annotations

from datetime import date

from . import gpx, places, sports
from .auth import GarminUnavailable, garmin_token
from .garmin_courses import Client, GarminError
from .i18n import N_, gettext
from .sources import Fetched, SourceError

PAGE = 30
MIN_SPACING_M = 8
MULTI = "multi_sport"
SOURCE = "garmin_activity"
# the sport filter of the page: Garmin's parent types (they take their sub types)
FILTERS = {"": N_("All sports"), "cycling": N_("Cycling"), "running": N_("Running"),
           "walking": N_("Walking"), "hiking": N_("Hiking")}
NOT_SHARED = N_("Garmin does not share this activity with you. Only your own and public "
                "activities can be added.")


def clean(points: list) -> list:
    """Without the knots of standing still: a point closer than
    MIN_SPACING_M to the last one kept goes; the last point always stays."""
    if len(points) < 3:
        return list(points)
    kept = [points[0]]
    for p in points[1:-1]:
        if gpx.haversine(kept[-1], p) >= MIN_SPACING_M:
            kept.append(p)
    kept.append(points[-1])
    return kept


def scheme_name(points: list, sport: str, fallback: str) -> str:
    """"Starnberg via Percha 42k 380hm" (loop) / "München to Schliersee
    118k 1240hm"; without the local place list the activity's own name."""
    st = gpx.stats(gpx.Track(points=points))
    head = places.route_head(points, not st["loop"]) or fallback.strip() or "Route"
    return f"{head} {sports.km_label(st['distance_m'] / 1000, sport)}k {st['ascent_m'] or 0}hm"


def _sport(type_key: str | None) -> list[str]:
    return [type_key] if type_key in sports.BY_KEY else []


async def _client(uid: int | None) -> Client:
    try:
        return Client(await garmin_token(uid))
    except GarminUnavailable as e:
        raise SourceError(e.text) from e


def _source_error(exc: GarminError) -> SourceError:
    if exc.status in (401, 403):
        return SourceError(NOT_SHARED)
    if exc.status is None:
        return SourceError(N_("{source} is not reachable right now."), source="Garmin Connect")
    return SourceError(N_("{source} answered with an error ({status})."),
                       source="Garmin Connect", status=exc.status)


async def fetch(activity_id: str, uid: int | None, lang: str, url: str = "") -> Fetched:
    """One activity (or one part of a multisport one) as a route to create."""
    garmin = await _client(uid)
    try:
        detail = await garmin.activity(activity_id)
        if detail is None:
            raise SourceError(NOT_SHARED)
        type_key = (detail.get("activityTypeDTO") or {}).get("typeKey") or ""
        if type_key == MULTI:
            raise SourceError(N_("This is a multisport activity: take its parts one by one "
                                 "under “From Garmin”."))
        data = await garmin.activity_gpx(activity_id)
    except GarminError as exc:
        raise _source_error(exc) from exc
    try:
        points = clean(gpx.parse(data).points)
    except gpx.GpxError as exc:
        raise SourceError(N_("This activity has no GPS track.")) from exc
    name = (detail.get("activityName") or "").strip()
    sport = _sport(type_key)
    day = (detail.get("summaryDTO") or {}).get("startTimeLocal", "")[:10]
    when = day_label(day, lang)
    title = scheme_name(points, sport[0] if sport else "", name)
    description = gettext(lang, N_("From the Garmin activity “{name}” on {date}."),
                          name=name or "?", date=when)
    return Fetched(data=gpx.write(title, points), source=SOURCE,
                   source_url=url or f"https://connect.garmin.com/modern/activity/{activity_id}",
                   external_id=str(activity_id), name=title, description=description,
                   sports=sport)


def day_label(day: str, lang: str) -> str:
    try:
        d = date.fromisoformat(day)
    except ValueError:
        return day
    return d.strftime("%d.%m.%Y") if lang == "de" else d.strftime("%b %-d, %Y")


def _item(a: dict, parent: str = "") -> dict:
    type_key = (a.get("activityType") or a.get("activityTypeDTO") or {}).get("typeKey") or ""
    summary = a.get("summaryDTO") or a
    return {"id": a.get("activityId"), "name": a.get("activityName") or "",
            "day": (summary.get("startTimeLocal") or "")[:10], "type": type_key,
            "km": (summary.get("distance") or 0) / 1000,
            "up": round(summary.get("elevationGain") or 0), "parent": parent}


async def page(uid: int | None, start: int = 0, sport: str = "", since: str = "",
               until: str = "") -> tuple[list[dict], bool]:
    """A page of the user's activities with GPS, newest first, a multisport
    one with its parts below it ([{id, name, day, type, km, up, parent}]),
    and whether there are older ones. Raises SourceError."""
    garmin = await _client(uid)
    try:
        found = await garmin.activities(start, PAGE, sport or None, since or None, until or None)
        out = []
        for a in found:
            type_key = (a.get("activityType") or {}).get("typeKey")
            if type_key == MULTI:
                parent = _item(a)
                out.append({**parent, "multi": True})
                for child_id in (a.get("childIds") or []) or await _child_ids(garmin, a):
                    child = await garmin.activity(child_id)
                    if child and (child.get("metadataDTO") or {}).get("hasPolyline", True):
                        out.append({**_item({**child, "activityId": child_id}),
                                    "parent": parent["name"]})
            elif a.get("hasPolyline") and not a.get("parentId"):   # parts come with their parent
                out.append(_item(a))
    except GarminError as exc:
        raise _source_error(exc) from exc
    return out, len(found) == PAGE


async def _child_ids(garmin: Client, a: dict) -> list:
    detail = await garmin.activity(a["activityId"])
    return ((detail or {}).get("metadataDTO") or {}).get("childIds") or []
