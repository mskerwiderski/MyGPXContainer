"""Komoot tours: komoot's public API with the share link's token
(`api/v007/tours/<id>?share_token=…&_embedded=coordinates`, tried live
2026-10-27). A private tour without its share_token answers 403."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

import httpx

from .. import gpx
from ..i18n import N_
from . import Fetched, SourceError

API = "https://www.komoot.com/api/v007/tours/{id}"

# komoot sport -> Garmin typeKey (sports.py); anything else: the user picks
SPORT = {
    "jogging": "running", "hike": "hiking", "mountaineering": "hiking",
    "racebike": "road_biking", "touringbicycle": "cycling",
    "mtb_easy": "gravel_cycling", "mtb": "mountain_biking", "mtb_advanced": "enduro_mtb",
    "e_racebike": "e_bike_fitness", "e_touringbicycle": "e_bike_fitness",
    "e_mtb_easy": "e_bike_fitness", "e_mtb": "e_bike_mountain", "e_mtb_advanced": "e_enduro_mtb",
}


async def _get_json(url: str, params: dict) -> tuple[int, dict]:
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        r = await client.get(url, params=params)   # an Accept header gets 406
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {}


async def fetch(url: str) -> Fetched:
    m = re.search(r"/tour/(\d+)", urlsplit(url).path)
    if not m:
        raise SourceError(N_("This Komoot link does not point to a tour."))
    tour_id = m.group(1)
    params = {"_embedded": "coordinates"}
    token = parse_qs(urlsplit(url).query).get("share_token", [""])[0]
    if token:
        params["share_token"] = token
    try:
        status, body = await _get_json(API.format(id=tour_id), params)
    except httpx.HTTPError as exc:
        raise SourceError(N_("{source} is not reachable right now."), source="Komoot") from exc
    if status in (401, 403):
        raise SourceError(N_("Komoot does not share this tour. Use the share link from "
                             "Komoot's “Share” button - it carries an access token."))
    if status == 404:
        raise SourceError(N_("Komoot does not know this tour."))
    if status != 200:
        raise SourceError(N_("{source} answered with an error ({status})."),
                          source="Komoot", status=status)
    items = ((body.get("_embedded") or {}).get("coordinates") or {}).get("items") or []
    points = [(p["lat"], p["lng"], p.get("alt")) for p in items
              if isinstance(p.get("lat"), (int, float)) and isinstance(p.get("lng"), (int, float))]
    if len(points) < 2:
        raise SourceError(N_("The tour has no track."))
    name = (body.get("name") or "").strip() or f"Komoot {tour_id}"
    sport = SPORT.get(body.get("sport") or "")
    return Fetched(data=gpx.write(name, points), source="komoot", source_url=url,
                   external_id=tour_id, name=name, sports=[sport] if sport else [])
