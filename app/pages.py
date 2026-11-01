"""Pages: route list, upload, detail with map and profile, edit, delete,
download, share. Everything is the signed-in user's own: someone else's
route or folder is answered with 404, as if it did not exist."""

from __future__ import annotations

import asyncio
import math
import re
import time
import unicodedata
from datetime import datetime, timezone
from functools import lru_cache
from urllib.parse import quote, urlencode

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlmodel import select

from . import (
    auth,
    folders,
    garmin_courses,
    garmin_sync,
    geocode,
    gpx,
    places,
    routes,
    routing,
    search,
    sources,
    sports,
    store,
    suggest,
    waytypes,
    web,
)
from .db import get_session
from .i18n import N_, gettext
from .models import Route, now_utc
from .sports import BY_KEY, GROUPS, PROFILES, SPORTS, profile

router = APIRouter()
MAX_FILES = 50


def _folders(request: Request) -> dict:
    with get_session() as s:
        return {"folders": folders.all_folders(s, _user(request)),
                "default_folder": folders.DEFAULT_NAME}


def _ctx() -> dict:
    return {"sports": SPORTS, "sport_by_key": BY_KEY, "groups": GROUPS, "max_files": MAX_FILES,
            "profiles": PROFILES, "profile": profile, "sketch": _sketch}


def _not_found(request: Request):
    return web.error(request, 404, N_("Route not found"),
                     N_("It may have been deleted in the meantime."))


def _user(request: Request) -> dict | None:
    return getattr(request.state, "user", None)


def _garmin_user(request: Request) -> dict | None:
    """The signed-in user, if Garmin can work for them (uid + username)."""
    user = _user(request)
    return user if user and user.get("uid") is not None and user.get("username") else None


@router.get("/")
async def route_list(request: Request):
    """The list with filters (search.py). The filter form and the list view
    switch fetch this page again and swap #results (app.js)."""
    user = _garmin_user(request)
    me = _user(request)
    f = search.Filters.parse(request.query_params)
    center, place_label, place_missing = None, "", False
    if f.lat is not None:
        center = (f.lat, f.lon)
    elif f.place:
        hit = await geocode.lookup(f.place, web.lang(request))
        if hit:
            place_label, center = hit[0], (hit[1], hit[2])
        else:
            place_missing = True
    with get_session() as s:
        all_routes = routes.own(s, me)
        rows = garmin_sync.rows_of(s, user) if user else []
        folder_counts = folders.counts(s, me)
    by_uid = {r.uid: r for r in all_routes}
    mine = {r.route_uid for r in rows}
    # "current" or "changed" per route uid: the G badge shows which is which
    garmin_state = {r.route_uid: garmin_sync.state(r, by_uid.get(r.route_uid)) for r in rows}
    found = search.apply(all_routes, f, in_garmin=mine, center=center)
    senders = sorted({(r.shared_by_username, r.shared_by_name or r.shared_by_username)
                      for r in all_routes if r.shared_from}, key=lambda c: c[1].casefold())
    starts = [{"id": r.id, "name": r.name, "lat": r.start_lat, "lon": r.start_lon,
               "km": round(r.distance_m / 1000, 1), "up": r.ascent_m,
               "line": _outline(r.gpx_sha, r.reversed)} for r, _ in found] if f.view == "map" else []
    q = request.query_params
    bulk = {"done": q.get("done", ""), "n": q.get("n", "0")}
    return web.render(request, "routes.html", found=found, total=len(all_routes), f=f,
                      in_garmin=mine, garmin_state=garmin_state,
                      folder_counts=folder_counts, bulk=bulk, query=_filter_query(q),
                      **_folders(request), senders=senders, me=user, center=center,
                      place_label=place_label, place_missing=place_missing,
                      starts_json=web.script_json(starts),
                      radii=search.RADII, **_ctx())


def _filter_query(params) -> str:
    """The list's own query string without the bulk message (bulk.html)."""
    return urlencode([(k, v) for k, v in params.multi_items()
                      if k not in ("done", "n")])


@router.post("/routes/bulk")
async def routes_bulk(request: Request, action: str = Form(...), ids: list[int] = Form([]),
                      folder: str = Form(""), back: str = Form("")):
    """Several routes at once (selection mode of the list): move them to a
    folder, delete them (their Garmin courses stay - "My Garmin" removes
    them) or go on to send them to Garmin or share them. Only the user's own."""
    with get_session() as s:
        chosen = [r for r in (routes.get_own(s, _user(request), i) for i in dict.fromkeys(ids))
                  if r]
        n = 0
        if action in ("share", "garmin"):
            return RedirectResponse(("/routes/share?" if action == "share" else "/garmin/send?")
                                    + urlencode([("ids", r.id) for r in chosen]
                                                + [("back", "/?" + back if back else "/")]),
                                    status_code=303)
        if action == "move":
            target = folders.valid_id(s, _user(request), folder)
            for r in chosen:
                r.folder_id = target
                s.add(r)
                n += 1
            s.commit()
        elif action == "delete":
            for r in chosen:
                routes.delete(s, r)
                n += 1
        else:
            return web.error(request, 422, N_("Unknown action"))
    sep = "&" if back else ""
    return RedirectResponse(f"/?{back}{sep}done={action}&n={n}",
                            status_code=303)


@router.get("/routes/new")
def route_new(request: Request):
    return web.render(request, "route_new.html", **_ctx(), **_folders(request),
                      folder_pre=request.query_params.get("folder", ""))


@router.post("/routes")
async def route_upload(request: Request, files: list[UploadFile] = File(...),
                       sports: list[str] = Form([]), description: str = Form(""),
                       folder: str = Form("")):
    files_data = [(f.filename, await f.read(gpx.MAX_BYTES + 1)) for f in files[:MAX_FILES]]
    # parsing 50 big files takes a while: not on the event loop (security review)
    results = await asyncio.to_thread(_store_uploads, _user(request), folder, files_data,
                                      sports, description)
    if len(results) == 1 and results[0][1]:
        return RedirectResponse(f"/routes/{results[0][1].id}", status_code=303)
    return web.render(request, "route_upload_result.html", results=results,
                      too_many=len(files) > MAX_FILES, **_ctx())


def _store_uploads(user: dict | None, folder: str, files_data: list, sports: list[str],
                   description: str) -> list:
    results = []   # (filename, route | None, duplicate | None, error | None)
    with get_session() as s:
        folder_id = folders.valid_id(s, user, folder)
        for filename, data in files_data:
            try:
                route = routes.create(s, data, filename=filename or "", description=description,
                                      sport_keys=sports, user=user, folder_id=folder_id)
                results.append((filename, route, None, None))
            except routes.Duplicate as d:
                results.append((filename, None, d.route, None))
            except gpx.GpxError as e:
                results.append((filename, None, None, str(e)))
    return results


@router.post("/routes/link")
async def route_from_link(request: Request, url: str = Form(...), sports: list[str] = Form([]),
                          description: str = Form(""), folder: str = Form("")):
    """A route from a share link. Sports left empty take the source's own."""
    def again(problem: str, **values):
        return web.render(request, "route_new.html", 422, link_url=url, link_problem=problem,
                          link_values=values, folder_pre=folder, **_ctx(), **_folders(request))
    try:
        got = await sources.fetch(url, auth.uid(request))
    except sources.SourceError as e:
        return again(e.text, **e.values)
    with get_session() as s:
        try:
            route = routes.create(s, got.data, filename=got.filename, name=got.name,
                                  description=description or got.description,
                                  sport_keys=sports or got.sports, user=_user(request),
                                  source=got.source, source_url=got.source_url,
                                  external_id=got.external_id,
                                  folder_id=folders.valid_id(s, _user(request), folder))
        except gpx.GpxError as e:
            return again(str(e))
        except routes.Duplicate as d:
            return again(N_("This route is already here: “{name}”."), name=d.route.name,
                         route_id=d.route.id)
    return RedirectResponse(f"/routes/{route.id}", status_code=303)


# ---------- sharing: a copy for someone else ----------

def _back(value: str, default: str = "/") -> str:
    """A local path to go back to (never another host)."""
    return value if web.local_path(value) else default


async def _share_page(request: Request, ids: list[int], back: str, status_code: int = 200,
                      people: list[dict] | None = None, to: list[int] = (),
                      result: list | None = None, problem: str = ""):
    user = _user(request)
    with get_session() as s:
        chosen = [r for r in (routes.get_own(s, user, i) for i in dict.fromkeys(ids)) if r]
    if not chosen:
        return _not_found(request)
    if people is None:
        try:
            people = await auth.others(user)
        except auth.SharingUnavailable as e:
            people, problem = [], e.text
    back = _back(back, f"/routes/{chosen[0].id}" if len(chosen) == 1 else "/")
    return web.render(request, "share.html", status_code, chosen=chosen, people=people,
                      picked=set(to), result=result, problem=problem,
                      back=back, back_path=back.split("?")[0])


@router.get("/routes/share")
async def share_page(request: Request):
    q = request.query_params
    ids = [int(i) for i in q.getlist("ids") if i.isdigit()]
    return await _share_page(request, ids, q.get("back", ""))


@router.post("/routes/share")
async def share_routes(request: Request, ids: list[int] = Form([]), to: list[int] = Form([]),
                       back: str = Form("")):
    """Copies of the user's routes for the people picked - only people MyAuth
    lists for the app, whatever the form says. Someone who has a route already
    (same file, same tour, an earlier copy) gets no second one."""
    user = _user(request)
    try:
        people = await auth.others(user)
    except auth.SharingUnavailable as e:
        return await _share_page(request, ids, back, 503, people=[], problem=e.text)
    recipients = [m for m in people if m["uid"] in set(to)]
    if not recipients:
        return await _share_page(request, ids, back, 422, people=people, to=to,
                                 problem=N_("Pick at least one person."))
    result = []      # (name, shared, had)
    with get_session() as s:
        chosen = [r for r in (routes.get_own(s, user, i) for i in dict.fromkeys(ids)) if r]
        if not chosen:
            return _not_found(request)
        for m in recipients:
            got = [routes.share(s, r, m, user) for r in chosen]
            shared = sum(1 for c in got if c)
            result.append((m["display_name"], shared, len(got) - shared))
        s.commit()
    return await _share_page(request, ids, back, people=people, result=result)


# cached per file AND direction (a turned route draws the other way round)
def _track(sha: str, reversed_: bool) -> gpx.Track:
    track = gpx.parse(store.get(sha))
    return gpx.reverse(track) if reversed_ else track


@lru_cache(maxsize=2048)
def _sketch_of(sha: str, reversed_: bool) -> dict:
    return gpx.sketch(_track(sha, reversed_))


def _sketch(route: Route) -> dict:
    return _sketch_of(route.gpx_sha, route.reversed)


@lru_cache(maxsize=2048)
def _outline(sha: str, reversed_: bool) -> list:
    return gpx.outline(_track(sha, reversed_))


@lru_cache(maxsize=64)
def _display(sha: str, reversed_: bool) -> str:
    return web.script_json(gpx.display(_track(sha, reversed_)))


@router.get("/routes/{route_id}")
async def route_detail(request: Request, route_id: int):
    with get_session() as s:
        route = routes.get_own(s, _user(request), route_id)
    if not route:
        return _not_found(request)
    user = _garmin_user(request)
    with get_session() as s:
        row = garmin_sync.row_for(s, user, route.uid) if user else None
        prefs = garmin_sync.prefs_of(s, user) if user else None
    with get_session() as s:
        folder = folders.get_own(s, _user(request), route.folder_id) if route.folder_id else None
    return web.render(request, "route.html", route=route,
                      ways=await _ways(route, request.query_params.get("ways") == "1"),
                      track_json=_display(route.gpx_sha, route.reversed),
                      folder=folder, default_folder=folders.DEFAULT_NAME,
                      garmin_user=user, garmin_row=row,
                      garmin_st=garmin_sync.state(row, route) if row else None,
                      garmin_run=garmin_sync.run_state(user["uid"]) if user else None,
                      course_url=garmin_sync.course_url,
                      on_devices=garmin_sync.on_devices(prefs, row) if row else [],
                      **_ctx())


def _way_slot(kind: str, key: str) -> str:
    """The colour class of a category: its place in the fixed order (app.css)."""
    keys = [k for k, _, _ in (waytypes.WAY if kind == "way" else waytypes.SURFACE)]
    return f"series-{keys.index(key) + 1}" if key in keys else "series-unknown"


async def _ways(route: Route, ask: bool) -> dict | None:
    """The way types panel: None = no routing service; pending = the page
    asks for `?ways=1` after it is shown (GraphHopper takes a second or
    two the first time); else data or the problem."""
    if not waytypes.available():
        return None
    out = {"slot": _way_slot, "label": waytypes.label, "pending": False, "problem": ""}
    try:
        data = await waytypes.for_route(route) if ask else (waytypes.known(route) or {}).get("data")
    except waytypes.Unavailable as e:
        return {**out, "problem": e.text}
    if data is None:
        hit = waytypes.known(route)
        if hit and "error" in hit:
            return {**out, "problem": hit["error"]}
        return {**out, "pending": True}
    return {**out, "data": data, "json": web.script_json(data)}


@router.get("/routes/{route_id}/edit")
def route_edit(request: Request, route_id: int):
    with get_session() as s:
        route = routes.get_own(s, _user(request), route_id)
    if not route:
        return _not_found(request)
    return web.render(request, "route_edit.html", route=route, **_ctx(), **_folders(request))


@router.post("/routes/{route_id}/edit")
async def route_save(request: Request, route_id: int, name: str = Form(...),
                     description: str = Form(""), sports: list[str] = Form([]),
                     folder: str = Form(""), file: UploadFile | None = File(None)):
    with get_session() as s:
        route = routes.get_own(s, _user(request), route_id)
        if not route:
            return _not_found(request)
        data = await file.read(gpx.MAX_BYTES + 1) if file and file.filename else None
        try:
            routes.update(s, route, name=name, description=description, sport_keys=sports,
                          data=data, folder_id=folders.valid_id(s, _user(request), folder))
        except (gpx.GpxError, routes.Duplicate) as e:
            s.rollback()
            s.refresh(route)
            problem = (str(e) if isinstance(e, gpx.GpxError)
                       else N_("This GPX file is already the route “{name}”."))
            dup = e.route if isinstance(e, routes.Duplicate) else None
            return web.render(request, "route_edit.html", 422, route=route, problem=problem,
                              duplicate=dup, **_ctx(), **_folders(request))
    return RedirectResponse(f"/routes/{route_id}", status_code=303)


@router.post("/routes/{route_id}/delete")
def route_delete(request: Request, route_id: int):
    with get_session() as s:
        route = routes.get_own(s, _user(request), route_id)
        if not route:
            return _not_found(request)
        routes.delete(s, route)
    return RedirectResponse("/", status_code=303)


def _filename(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return (re.sub(r"[^A-Za-z0-9]+", "_", ascii_name).strip("_") or "route") + ".gpx"


@router.post("/routes/{route_id}/reverse")
def route_reverse(request: Request, route_id: int):
    """The other way round (start and finish swap); the page swaps its parts."""
    with get_session() as s:
        route = routes.get_own(s, _user(request), route_id)
        if not route:
            return _not_found(request)
        routes.turn_round(s, route)
    return RedirectResponse(f"/routes/{route_id}", status_code=303)


@router.post("/routes/{route_id}/copy")
def route_copy(request: Request, route_id: int):
    """A second route from the same one, then its page (to rename or change it)."""
    with get_session() as s:
        route = routes.get_own(s, _user(request), route_id)
        if not route:
            return _not_found(request)
        twin = routes.copy(s, route, gettext(web.lang(request), N_("{name} (copy)"),
                                             name=route.name))
    return RedirectResponse(f"/routes/{twin.id}?copied=1", status_code=303)


@router.get("/routes/{route_id}/gpx")
def route_download(request: Request, route_id: int):
    with get_session() as s:
        route = routes.get_own(s, _user(request), route_id)
    if not route:
        return _not_found(request)
    name = _filename(route.name)
    return Response(routes.gpx_bytes(route), media_type="application/gpx+xml",
                    headers={"Content-Disposition":
                             f"attachment; filename=\"{name}\"; filename*=UTF-8''{quote(name)}"})


# ---------- route suggestions (suggest.py, places.py) ----------

_LOOP_POINTS = 600          # per route on the page map
_PROFILE_POINTS = 150       # per elevation profile on a card
_PROFILE_W, _PROFILE_H = 100, 40
_PROFILE_MIN_RANGE_M = 60   # a flat route must not look hilly


def _profiles(loops: list) -> list[dict]:
    """The cards' elevation profiles as SVG paths, all on ONE scale - the same
    km and metres - so the three can be compared at a glance: {"line",
    "area", "lo", "hi"} (the route's own lowest and highest point)."""
    shown = []
    for lp in loops:
        prof = gpx.display(gpx.Track(points=lp.points), map_points=2,
                           profile_points=_PROFILE_POINTS)["profile"]
        shown.append((prof["km"], prof["ele"]))
    eles = [e for _, ele in shown for e in ele]
    if not eles:
        return [None for _ in loops]
    longest = max((km[-1] for km, _ in shown if km), default=0) or 1
    lo, hi = min(eles), max(eles)
    pad = max(0.0, _PROFILE_MIN_RANGE_M - (hi - lo)) / 2
    lo, hi = lo - pad, hi + pad
    out = []
    for km, ele in shown:
        if len(km) < 2:
            out.append(None)
            continue
        xy = [(round(k / longest * _PROFILE_W, 2),
               round(_PROFILE_H - (e - lo) / (hi - lo) * _PROFILE_H, 2)) for k, e in zip(km, ele)]
        line = "M" + " L".join(f"{x} {y}" for x, y in xy)
        out.append({"line": line, "area": f"{line} L{xy[-1][0]} {_PROFILE_H} L{xy[0][0]} {_PROFILE_H} Z",
                    "lo": round(min(ele)), "hi": round(max(ele))})
    return out


def _coord(value) -> float | None:
    try:
        f = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _point(q, lat_key: str = "lat", lon_key: str = "lon") -> tuple[float, float] | None:
    lat, lon = _coord(q.get(lat_key)), _coord(q.get(lon_key))
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def _area(request: Request) -> tuple[float, float] | None:
    """Where the user's routes start (the median): to rank addresses nearby
    first when the form has no position yet."""
    with get_session() as s:
        own = routes.own(s, _user(request))
    if not own:
        return None
    lats, lons = sorted(r.start_lat for r in own), sorted(r.start_lon for r in own)
    return lats[len(lats) // 2], lons[len(lons) // 2]


async def _resolve(text: str, lang: str, near) -> tuple[str, tuple[float, float]] | None:
    """A typed place or address nobody picked from the list: Photon's first
    hit, else Open-Meteo's place search."""
    hits = await places.search(text, lang, near)
    if hits:
        return hits[0]["label"], (hits[0]["lat"], hits[0]["lon"])
    hit = await geocode.lookup(text, lang)
    return (hit[0], (hit[1], hit[2])) if hit else None


def _stops_from(values: list[str]) -> list[dict]:
    """The stops of the form, in their order: each "lat,lon,label" (lat/lon
    empty when nobody picked a hit - then the label is looked up)."""
    out = []
    for v in values[:suggest.STOPS_MAX]:
        lat, lon, label = (v.split(",", 2) + ["", ""])[:3]
        point = _point({"lat": lat, "lon": lon})
        label = label.strip()[:100]
        if point or label:
            out.append({"point": point, "label": label})
    return out


def _stop_value(stop: dict) -> str:
    lat, lon = stop["point"] if stop["point"] else ("", "")
    return f"{lat},{lon},{stop['label']}"


@router.get("/suggest/where")
def suggest_where(lat: str = "", lon: str = ""):
    """A name for a point tapped on the map (local place list, nothing leaves)."""
    point = _point({"lat": lat, "lon": lon})
    if not point:
        return {"label": ""}
    return {"label": places.label_at(*point), "lat": round(point[0], 5),
            "lon": round(point[1], 5)}


@router.get("/suggest/places")
async def suggest_places(request: Request, q: str = "", lat: str = "", lon: str = ""):
    """Addresses and places while typing (places.search): [{label, lat, lon}]."""
    near = _point({"lat": lat, "lon": lon}) or _area(request)
    return await places.search(q, web.lang(request), near)


@router.get("/suggest")
async def suggest_page(request: Request):
    """The form; with a sport, a start (location, picked or typed place) and
    the distance - or a destination for A to B - also three suggestions. The
    form sends itself with fetch and swaps #suggestions (app.js)."""
    q = request.query_params
    lang = web.lang(request)
    kind = "oneway" if q.get("kind") == "oneway" else "loop"
    sport = q.get("sport") if q.get("sport") in suggest.ENGINE else "cycling"
    wish = q.get("profile") if q.get("profile") in PROFILES else "flat"
    km = search._num(q.get("km"))
    place, to_place = q.get("place", "").strip()[:100], q.get("to_place", "").strip()[:100]
    start, finish = _point(q), _point(q, "to_lat", "to_lon")
    stops = _stops_from(q.getlist("via"))
    loops, problem, values, note = [], "", {}, None
    if len(q.getlist("via")) > suggest.STOPS_MAX:
        problem, values = N_("At most {max} stops."), {"max": suggest.STOPS_MAX}
    longest = suggest.limit(sport)
    if "sport" in q and (kind == "oneway" or km is not None) and not problem:
        if kind == "loop" and not suggest.MIN_KM <= km <= longest:
            problem, values = N_("Pick a distance from {min} to {max} km."), {
                "min": suggest.MIN_KM, "max": longest}
        elif start is None and place:
            hit = await _resolve(place, lang, _area(request))
            if hit:
                place, start = hit
            else:
                problem, values = N_("Place “{place}” not found"), {"place": place}
        elif start is None:
            problem = N_("Pick a start: your location or a place.")
        for stop in stops if not problem else []:
            if stop["point"] is None:
                hit = await _resolve(stop["label"], lang, start or _area(request))
                if not hit:
                    problem, values = N_("Place “{place}” not found"), {"place": stop["label"]}
                    break
                stop["label"], stop["point"] = hit
        points = [s["point"] for s in stops]
        if kind == "oneway" and not problem:
            if finish is None and to_place:
                hit = await _resolve(to_place, lang, start)
                if hit:
                    to_place, finish = hit
                else:
                    problem, values = N_("Place “{place}” not found"), {"place": to_place}
            elif finish is None:
                problem = N_("Pick a destination.")
            if finish and not problem:
                ring = [start, *points, finish]
                crow = sum(gpx.haversine(a, b) for a, b in zip(ring, ring[1:])) / 1000
                if crow < suggest.MIN_ONEWAY_KM:
                    problem, values = N_("Pick a destination at least {min} km away."), {
                        "min": suggest.MIN_ONEWAY_KM}
                elif crow > longest:
                    problem, values = N_("Start and destination are {crow} km apart - more than "
                                         "the {max} km a route may have."), {
                        "crow": round(crow), "max": longest}
        if not problem:
            try:
                if kind == "oneway":
                    loops = await suggest.oneway(sport, start, finish, wish, points)
                elif points:
                    loops, shortest = await suggest.suggest_stops(sport, start, points, km, wish)
                    if shortest > km * 1.1:
                        note = {"km": round(shortest)}
                else:
                    loops = await suggest.suggest(sport, start, km, wish)
            except suggest.Unavailable as e:
                st = routing.status()
                problem, values = e.text, e.values
                if st["state"] == "building" and not st.get("serving"):
                    problem = N_("The map is being built. Suggestions come back in a few minutes.")
            if not loops and not problem:
                problem = (N_("No way found from the start to the destination.") if kind == "oneway"
                           else N_("No loop found from here. Try another start or distance."))
    shown = [{"line": [[round(p[0], 5), round(p[1], 5)]
                       for p in (loop.points[i] for i in gpx._thin(len(loop.points), _LOOP_POINTS))]}
             for loop in loops]
    return web.render(request, "suggest.html", kind=kind, sport=sport, wish=wish, km=km,
                      place=place, to_place=to_place, start=start, finish=finish,
                      stops=stops, stop_value=_stop_value, stops_note=note,
                      located=bool(start and not q.get("place")), loops=loops, problem=problem,
                      problem_values=values, fits=suggest.fits(loops, wish),
                      offered=suggest.OFFERED, chips=suggest.CHIPS, limit=suggest.limit,
                      loop_sketch=lambda loop: gpx.sketch(gpx.Track(points=loop.points)),
                      elevations=_profiles(loops),
                      lines_json=web.script_json({"start": start, "finish": finish,
                                                  "stops": [s["point"] for s in stops
                                                            if s["point"]],
                                                  "loops": shown}), **_ctx())


def _km_label(km: float, sport: str) -> str:
    """Runs and walks with one decimal ("21.9k"), rides whole ("85k") - as on
    the routes renamed on 2026-10-27; a point, in every language."""
    return f"{km:.1f}" if sports.on_foot([sport]) else f"{km:.0f}"


def _town(label: str) -> str:
    """The town of a picked label: "Alte Bahnhofstraße, 82319 Starnberg" -> Starnberg."""
    parts = [p.strip() for p in label.split(",")]
    if len(parts) > 1 and re.match(r"\d{4,5} \S", parts[1]):
        return parts[1].split(" ", 1)[1]
    return parts[0]


def _name(loop: suggest.Loop, sport: str, oneway: bool, start_label: str, finish_label: str,
          stops: list[dict] = ()) -> str:
    """"Starnberg via Percha 42k 380hm" / "München to Schliersee 118k 1240hm",
    with stops "Starnberg via Percha, Andechs …"; the places from the local
    place list, without it the places the user typed or picked."""
    head = places.route_head(loop.points, oneway, [s["point"] for s in stops])
    if not head:
        a, b = _town(start_label), _town(finish_label)
        head = (f"{a or 'Start'} to {b or 'Finish'}" if oneway else a or "Loop")
        names = [n for n in dict.fromkeys(_town(s["label"]) for s in stops) if n]
        if names:
            head += " via " + ", ".join(names)
    return f"{head} {_km_label(loop.km, sport)}k {loop.ascent_m or 0}hm"


@router.post("/suggest/take")
async def suggest_take(request: Request, sport: str = Form(...), profile: str = Form("flat"),
                       lat: str = Form(...), lon: str = Form(...), kind: str = Form("loop"),
                       km: float = Form(0), heading: int = Form(0), to_lat: str = Form(""),
                       to_lon: str = Form(""), cand: str = Form(""), start_label: str = Form(""),
                       finish_label: str = Form(""), via: list[str] = Form([])):
    """One of the suggestions as the user's own route: computed again from the
    same parameters (GraphHopper gives the same route), nothing kept between."""
    start = _point({"lat": lat, "lon": lon})
    finish = _point({"lat": to_lat, "lon": to_lon})
    oneway = kind == "oneway"
    stops = _stops_from(via)
    points = [s["point"] for s in stops]
    bad = (sport not in suggest.ENGINE or profile not in PROFILES or start is None
           or len(via) > suggest.STOPS_MAX or None in points)
    if oneway:
        keys = suggest.STOPS_ONEWAY_KEYS if points else suggest.ONEWAY_KEYS
        bad = bad or finish is None or cand not in keys
    else:
        bad = (bad or not suggest.MIN_KM <= km <= suggest.limit(sport) * suggest.ASK_SPAN
               or (not suggest.stops_key_ok(cand) if points else heading not in suggest.HEADINGS))
    if bad:
        return web.error(request, 422, N_("Unknown suggestion"))
    try:
        if oneway:
            loop = await suggest.oneway_one(sport, start, finish, profile, cand, points)
        elif points:
            loop = await suggest.stops_loop_one(sport, start, points, profile, cand, km)
        else:
            loop = await suggest.one(sport, start, km, profile, heading)
    except suggest.Unavailable as e:
        return web.error(request, 503, N_("No suggestion"), e.text)
    if loop is not None and oneway and loop.km > suggest.limit(sport):
        loop = None
    if loop is None:
        return web.error(request, 404, N_("No suggestion"),
                         N_("No way found from the start to the destination.") if oneway
                         else N_("No loop found from here. Try another start or distance."))
    lang = web.lang(request)
    name = _name(loop, sport, oneway, start_label[:100], finish_label[:100], stops)
    description = gettext(lang, N_("Suggested by MyGPXContainer on {date}: {sport}, {profile}."),
                          date=web.date(request, lang, now_utc()),
                          sport=gettext(lang, BY_KEY[sport].label),
                          profile=gettext(lang, PROFILES[profile]))
    with get_session() as s:
        try:
            route = routes.create(s, gpx.write(name, loop.points), name=name,
                                  description=description, sport_keys=[sport],
                                  user=_user(request), source="generated")
        except routes.Duplicate as d:
            route = d.route
    return RedirectResponse(f"/routes/{route.id}", status_code=303)


# ---------- Garmin: the signed-in user's own account ----------

def _sign_in_needed(request: Request):
    return web.error(request, 403, N_("Sign in needed"),
                     N_("Garmin works with your own account, so MyGPXContainer needs to know "
                        "who you are."))


_device_tries: dict[tuple[int, str], float] = {}
DEVICE_RETRY_S = 600


async def _load_devices(user: dict) -> None:
    """The user's OWN devices (their token, stored under their uid and
    username): "Send to Garmin" fetches them while none are known, "My
    Garmin" keeps the list current. Without any (no course-capable device,
    Garmin not connected) it asks again only every DEVICE_RETRY_S."""
    key = (user["uid"], user["username"])
    if time.monotonic() - _device_tries.get(key, -DEVICE_RETRY_S) < DEVICE_RETRY_S:
        return
    _device_tries[key] = time.monotonic()
    try:
        devices = await garmin_courses.Client(await auth.garmin_token(user["uid"])).devices()
    except (auth.GarminUnavailable, garmin_courses.GarminError):
        return
    with get_session() as s:
        garmin_sync.remember_devices(s, garmin_sync.prefs_of(s, user), devices)


async def _send_page(request: Request, user: dict, ids: list[int], back: str,
                     status_code: int = 200, **extra):
    with get_session() as s:
        chosen = [r for r in (routes.get_own(s, user, i) for i in dict.fromkeys(ids)) if r]
        if not chosen:
            return _not_found(request)
        rows = {r.route_uid: r for r in garmin_sync.rows_of(s, user)}
        known = garmin_sync.prefs_of(s, user).devices
    if not known:
        await _load_devices(user)
    with get_session() as s:
        devices = garmin_sync.prefs_of(s, user).devices
    back = _back(back, f"/routes/{chosen[0].id}" if len(chosen) == 1 else "/")
    sport_keys = [x.key for x in SPORTS]
    items = []                     # (route, sport choices, the one picked, already there)
    for r in chosen:
        choices = r.sports or sport_keys
        row = rows.get(r.uid)
        picked = row.activity_type if row and row.activity_type in choices else choices[0]
        items.append((r, choices, picked, row))
    again = urlencode([("ids", r.id) for r in chosen] + [("back", back), ("sent", "1")])
    return web.render(request, "garmin_send.html", status_code, items=items, devices=devices,
                      back=back, back_path=back.split("?")[0], again="/garmin/send?" + again,
                      run=garmin_sync.run_state(user["uid"]), **extra, **_ctx())


@router.get("/garmin/send")
async def garmin_send_page(request: Request):
    """Send one or several routes to Garmin Connect, and on to devices if
    the user ticks any (from the route and from the list's selection bar)."""
    user = _garmin_user(request)
    if not user:
        return _sign_in_needed(request)
    q = request.query_params
    ids = [int(i) for i in q.getlist("ids") if i.isdigit()]
    return await _send_page(request, user, ids, q.get("back", ""), sent=q.get("sent") == "1")


@router.post("/garmin/send")
async def garmin_send(request: Request):
    user = _garmin_user(request)
    if not user:
        return _sign_in_needed(request)
    form = await request.form()
    ids = [int(i) for i in form.getlist("ids") if str(i).isdigit()]
    back = str(form.get("back", ""))
    with get_session() as s:
        chosen = [r for r in (routes.get_own(s, user, i) for i in dict.fromkeys(ids)) if r]
        known = [d["id"] for d in garmin_sync.prefs_of(s, user).devices]
    if not chosen:
        return _not_found(request)
    items = []
    for r in chosen:
        sport = str(form.get(f"sport_{r.id}", ""))
        if sport not in BY_KEY:
            return web.error(request, 422, N_("Unknown sport"))
        items.append((r.uid, sport))
    try:
        devices = known if form.get("all_devices") else [int(d) for d in form.getlist("device")]
    except ValueError:
        return web.error(request, 422, N_("Unknown device"))
    if any(d not in known for d in devices):
        return web.error(request, 422, N_("Unknown device"))
    garmin_sync.start_send(user["uid"], user["username"], items, list(dict.fromkeys(devices)))
    return await _send_page(request, user, ids, back, sent=True)


@router.post("/garmin/remove")
async def garmin_remove(request: Request, ids: list[int] = Form([]),
                        every: str = Form("", alias="all"), back: str = Form("")):
    """Removes courses from the user's Garmin Connect: the rows picked on "My
    Garmin" (or all of them), or the one of a route (from its page)."""
    user = _garmin_user(request)
    if not user:
        return _sign_in_needed(request)
    with get_session() as s:
        mine = {r.id for r in garmin_sync.rows_of(s, user)}
    chosen = sorted(mine) if every else [i for i in dict.fromkeys(ids) if i in mine]
    if chosen:
        garmin_sync.start_remove(user["uid"], user["username"], chosen)
    return RedirectResponse(_back(back, "/garmin"), status_code=303)


@router.get("/garmin")
async def garmin_page(request: Request):
    """What MyGPXContainer put into the user's Garmin Connect. The page comes
    at once with what we know and "Checking Garmin Connect…"; garmin.js then
    asks `?fresh=1`, which first asks Garmin (`refresh`, a second or more)
    and is swapped in (Michael 2026-10-31: the user must see that something
    happens)."""
    user = _garmin_user(request)
    if not user:
        return _sign_in_needed(request)
    run = garmin_sync.run_state(user["uid"])
    fresh = request.query_params.get("fresh") == "1"
    problem = ""
    if fresh and not run.running:
        try:
            await garmin_sync.refresh(user["uid"], user["username"])
        except auth.GarminUnavailable as e:
            problem = e.text
        except garmin_courses.GarminError:
            problem = N_("Garmin Connect is not reachable right now - this is what it had last.")
    with get_session() as s:
        prefs = garmin_sync.prefs_of(s, user)
        rows = garmin_sync.rows_of(s, user)
        by_uid = {r.uid: r for r in s.exec(select(Route).where(
            *routes.owned_by(user), Route.uid.in_([row.route_uid for row in rows])))}
    items = sorted(((row, by_uid.get(row.route_uid)) for row in rows),
                   key=lambda x: (x[1] is None, (x[1].name if x[1] else x[0].name).lower()))
    return web.render(request, "garmin.html", items=items, state=garmin_sync.state, run=run,
                      problem=problem, checking=not fresh and not run.running, course_url=garmin_sync.course_url,
                      on_devices=lambda row: garmin_sync.on_devices(prefs, row), **_ctx())


@router.get("/garmin/status")
def garmin_status(request: Request):
    user = _garmin_user(request)
    run = garmin_sync.run_state(user["uid"]) if user else garmin_sync.Run()
    return {"running": run.running}


# ---------- map regions of the suggestions (app admins) ----------

_REGION_PROBLEMS = {N_("Unknown region"), N_("“{name}” is already covered by “{outer}”."),
                    N_("Geofabrik's list of regions is not reachable right now.")}


def _not_admin(request: Request):
    return web.error(request, 403, N_("Not allowed"), N_("Only app admins manage the maps."))


@router.get("/admin/routing")
async def routing_page(request: Request, q: str = ""):
    if not auth.is_admin(request):
        return _not_admin(request)
    with get_session() as s:
        rows = routing.regions(s)
    hits, problem, values = [], "", {}
    qp = request.query_params
    if qp.get("problem") in _REGION_PROBLEMS:
        problem = qp["problem"]
        values = {k: qp.get(k, "") for k in ("name", "outer")}
    if q.strip():
        try:
            hits = await routing.search(q, {r.geofabrik_id for r in rows})
        except routing.RegionError as e:
            problem, values = e.text, e.values
    return web.render(request, "admin_routing.html", rows=rows, st=routing.status(), q=q,
                      hits=hits, problem=problem, problem_values=values, step=_step,
                      when=lambda v: web.date(request, web.lang(request), _iso(v)))


def _step(text: str) -> tuple[str, dict]:
    """A build step of routing/run.py as an English key and its values."""
    if text.startswith("downloading "):
        return N_("downloading {name}"), {"name": text.removeprefix("downloading ")}
    return {"merging": N_("merging the regions"), "importing": N_("importing"),
            "switching": N_("switching to the new map")}.get(text, text), {}


def _iso(value) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


@router.post("/admin/routing/add")
async def routing_add(request: Request, region: str = Form(...)):
    if not auth.is_admin(request):
        return _not_admin(request)
    with get_session() as s:
        try:
            await routing.add(s, region, _user(request))
        except routing.RegionError as e:
            return RedirectResponse("/admin/routing?" + urlencode({"problem": e.text, **e.values}),
                                    status_code=303)
    return RedirectResponse("/admin/routing", status_code=303)


@router.post("/admin/routing/remove")
def routing_remove(request: Request, region: str = Form(...)):
    if not auth.is_admin(request):
        return _not_admin(request)
    with get_session() as s:
        routing.remove(s, region)
    return RedirectResponse("/admin/routing", status_code=303)


@router.post("/admin/routing/rebuild")
def routing_rebuild(request: Request):
    if not auth.is_admin(request):
        return _not_admin(request)
    with get_session() as s:
        routing.write(s, rebuild=True)
    return RedirectResponse("/admin/routing", status_code=303)


# ---------- folders ----------

@router.get("/folders")
def folder_page(request: Request, problem: str = ""):
    with get_session() as s:
        items = folders.all_folders(s, _user(request))
        counts = folders.counts(s, _user(request))
    return web.render(request, "folders.html", items=items, counts=counts,
                      default_folder=folders.DEFAULT_NAME,
                      problem=problem if problem in _FOLDER_PROBLEMS else "")


_FOLDER_PROBLEMS = {N_("A folder needs a name."), N_("There is already a folder with this name.")}


def _folder_problem(e: folders.FolderError) -> RedirectResponse:
    return RedirectResponse("/folders?" + urlencode({"problem": e.text}), status_code=303)


@router.post("/folders")
def folder_create(request: Request, name: str = Form("")):
    with get_session() as s:
        try:
            folders.create(s, name, _user(request))
        except folders.FolderError as e:
            return _folder_problem(e)
    return RedirectResponse("/folders", status_code=303)


@router.post("/folders/{folder_id}/rename")
def folder_rename(request: Request, folder_id: int, name: str = Form("")):
    with get_session() as s:
        folder = folders.get_own(s, _user(request), folder_id)
        if not folder:
            return web.error(request, 404, N_("Folder not found"))
        try:
            folders.rename(s, folder, name, _user(request))
        except folders.FolderError as e:
            return _folder_problem(e)
    return RedirectResponse("/folders", status_code=303)


@router.post("/folders/{folder_id}/delete")
def folder_delete(request: Request, folder_id: int):
    with get_session() as s:
        folder = folders.get_own(s, _user(request), folder_id)
        if not folder:
            return web.error(request, 404, N_("Folder not found"))
        folders.delete(s, folder)
    return RedirectResponse("/folders", status_code=303)
