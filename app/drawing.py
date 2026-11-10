"""Editing a route's way on the map (v1.6.0, Michael 2026-11-01).

The page `/routes/{id}/draw` (static/draw.js) gets the route's points the
way it goes and edits them in the browser: re-route a section over a point,
delete a section and join its ends, cut at the start or the end, extend
from the start or the end - over roads (our GraphHopper, `leg`) or as a
straight line; undo/redo. Whatever is not touched stays point for point.
While editing, `preview` gives km, climb and the profile from the elevation
model. Saving writes a new file (the model's heights, like every import,
routes.update / routes.create) - over the route, or as a copy beside it.
Only the owner's routes; the routing service only where it has maps.
"""

from __future__ import annotations

import asyncio
import json
import math

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from . import elevation, folders, gpx, routes, sports, suggest, web
from .config import get_settings
from .db import get_session
from .dem import DemUnavailable, terrain
from .i18n import N_, gettext
from .models import Route

router = APIRouter()

MAX_POINTS = 50_000
PREVIEW_PROFILE = 300


def _user(request: Request) -> dict | None:
    return getattr(request.state, "user", None)


def _own(request: Request, route_id: int) -> Route | None:
    with get_session() as s:
        return routes.get_own(s, _user(request), route_id)


def _points(value) -> list[tuple[float, float]] | None:
    """[[lat, lon], ...] from the browser, checked; None if it is not that."""
    if not isinstance(value, list) or not 2 <= len(value) <= MAX_POINTS:
        return None
    out = []
    for p in value:
        try:
            lat, lon = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            return None
        if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90
                and -180 <= lon <= 180):
            return None
        out.append((lat, lon))
    return out


def engine_of(route: Route) -> str:
    """The GraphHopper profile for the route's first sport (bike, else foot)."""
    for key in route.sports:
        if key in suggest.ENGINE:
            return suggest.ENGINE[key]
    return "foot" if sports.on_foot(route.sports) else "bike"


@router.get("/routes/{route_id}/draw")
def draw_page(request: Request, route_id: int):
    route = _own(request, route_id)
    if not route:
        return web.error(request, 404, N_("Route not found"),
                         N_("It may have been deleted in the meantime."))
    track = routes.track_of(route)
    data = {"points": [[round(p[0], 6), round(p[1], 6)] for p in track.points],
            "routing": bool(get_settings().routing_url)}
    return web.render(request, "draw.html", route=route, routing=data["routing"],
                      draw_json=web.script_json(data))


@router.post("/routes/{route_id}/draw/leg")
async def draw_leg(request: Request, route_id: int):
    """A stretch over roads through the given points ({"points": [[lat, lon]]},
    2 to 10 of them): {"points": [...]} or {"problem": text}."""
    route = _own(request, route_id)
    if not route:
        return JSONResponse({"problem": "not found"}, status_code=404)
    try:
        asked = _points((await request.json()).get("points"))
    except ValueError:
        asked = None
    if not asked or len(asked) > 10:
        return JSONResponse({"problem": "bad points"}, status_code=422)
    lang = web.lang(request)
    engine = engine_of(route)
    body = {"profile": engine, "points": [[p[1], p[0]] for p in asked], "ch.disable": True,
            "points_encoded": False, "instructions": False,
            "custom_model": {"priority": suggest.priority(engine)}}
    try:
        status, answer = await suggest._route(body)
        paths = suggest._paths(status, answer)
    except suggest.Unavailable as e:
        return JSONResponse({"problem": gettext(lang, e.text, **e.values)}, status_code=503)
    if not paths:
        return JSONResponse({"problem": gettext(lang, N_("No way found over roads here - try a "
                                                         "straight line."))}, status_code=404)
    coords = paths[0]["points"]["coordinates"]
    return {"points": [[round(c[1], 6), round(c[0], 6)] for c in coords]}


def _preview(points: list[tuple[float, float]]) -> dict:
    """km, climb and a profile of the edited way, heights from the model
    (blocking: a tile may load)."""
    try:
        heights = terrain.smoothed(points, elevation._sampler())
    except DemUnavailable:
        heights = None
    pts = [(lat, lon, h) for (lat, lon), h in zip(points, heights or [None] * len(points))]
    st = gpx.stats(gpx.Track(points=pts))
    prof = gpx.display(gpx.Track(points=pts), map_points=2,
                       profile_points=PREVIEW_PROFILE)["profile"] if heights else None
    return {"km": round(st["distance_m"] / 1000, 2), "up": st["ascent_m"],
            "down": st["descent_m"], "loop": st["loop"],
            "profile": {"km": prof["km"], "ele": prof["ele"]} if prof else None}


@router.post("/routes/{route_id}/draw/preview")
async def draw_preview(request: Request, route_id: int):
    if not _own(request, route_id):
        return JSONResponse({"problem": "not found"}, status_code=404)
    try:
        points = _points((await request.json()).get("points"))
    except ValueError:
        points = None
    if not points:
        return JSONResponse({"problem": "bad points"}, status_code=422)
    return await asyncio.to_thread(_preview, points)


@router.post("/routes/{route_id}/draw")
async def draw_save(request: Request, route_id: int, points: str = Form(""),
                    as_copy: str = Form("")):
    """The edited way: over the route (it now goes the way it is drawn), or
    as a copy beside it ("<name> (copy)")."""
    route = _own(request, route_id)
    if not route:
        return web.error(request, 404, N_("Route not found"),
                         N_("It may have been deleted in the meantime."))
    try:
        pts = _points(json.loads(points))
    except ValueError:
        pts = None
    if not pts:
        return web.error(request, 422, N_("The way could not be read."))
    user, lang = _user(request), web.lang(request)

    def save() -> Route:              # in a thread: the heights may load a tile
        with get_session() as s:
            own = routes.get_own(s, user, route_id)
            if as_copy:
                name = gettext(lang, N_("{name} (copy)"), name=own.name)
                data = gpx.write(name, [(lat, lon, None) for lat, lon in pts], own.description)
                try:
                    return routes.create(
                        s, data, name=name, description=own.description,
                        sport_keys=own.sports, user=user, source=own.source,
                        source_url=own.source_url,
                        folder_id=folders.valid_id(s, user, str(own.folder_id or "")))
                except routes.Duplicate as d:
                    return d.route
            data = gpx.write(own.name, [(lat, lon, None) for lat, lon in pts], own.description)
            try:
                routes.update(s, own, name=own.name, description=own.description,
                              sport_keys=own.sports, data=data, folder_id=own.folder_id)
            except routes.Duplicate as d:
                return d.route
            return own
    saved = await asyncio.to_thread(save)
    return RedirectResponse(f"/routes/{saved.id}?{'copied=1' if as_copy else 'drawn=1'}",
                            status_code=303)

