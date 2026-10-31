"""Routes: create from a GPX file, update, delete, share, copy, turn round.
Every route belongs to one user (Michael 2026-10-29): only they see and change
it. Sharing gives the other user a copy of their own - later changes on
either side stay there.

Turning a route round (v1.1.0) keeps the uploaded file byte-identical and
only sets `Route.reversed`: whoever reads the track goes through `track_of`
(map, profile, sketch, figures) or `gpx_bytes` (download, Garmin), never
through the store directly."""

from __future__ import annotations

import hashlib
import uuid

from sqlmodel import Session, or_, select

from . import gpx, sports, store
from .models import Route, now_utc


def store_sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------- whose route ----------

def owner(user: dict | None) -> tuple[int | None, str]:
    """The owner key of a user: MyAuth uid AND username (a rebuilt MyAuth may
    give the uid to someone else). Without login (local development) (None, "")."""
    user = user or {}
    return user.get("uid"), user.get("username") or ""


def _owner_is(uid: int | None, username: str) -> tuple:
    return (Route.created_by_uid == uid if uid is not None else Route.created_by_uid.is_(None),
            Route.created_by_username == username)


def owned_by(user: dict | None) -> tuple:
    """WHERE conditions: the routes of `user`."""
    return _owner_is(*owner(user))


def owns(route: Route, user: dict | None) -> bool:
    return (route.created_by_uid, route.created_by_username) == owner(user)


def own(session: Session, user: dict | None) -> list[Route]:
    return list(session.exec(select(Route).where(*owned_by(user))))


def get_own(session: Session, user: dict | None, route_id: int) -> Route | None:
    """The user's route with this id; None also for someone else's (the
    pages answer 404 - nobody learns that it exists)."""
    route = session.get(Route, route_id)
    return route if route and owns(route, user) else None


class Duplicate(Exception):
    def __init__(self, route: Route):
        self.route = route


def track_of(route: Route) -> gpx.Track:
    """The track the way the route goes (reversed if it is turned round)."""
    track = gpx.parse(store.get(route.gpx_sha))
    return gpx.reverse(track) if route.reversed else track


def gpx_bytes(route: Route) -> bytes:
    """The GPX file the way the route goes: the uploaded file as it is, or -
    turned round - a new one with the points reversed (without times)."""
    data = store.get(route.gpx_sha)
    if not route.reversed:
        return data
    track = gpx.reverse(gpx.parse(data))
    return gpx.write(route.name, track.points, route.description)


def turn_round(session: Session, route: Route) -> Route:
    """The other way round: start and finish swap, ascent and descent too."""
    route.reversed = not route.reversed
    for k, v in gpx.stats(track_of(route)).items():
        setattr(route, k, v)
    route.updated_at = now_utc()
    session.add(route)
    session.commit()
    session.refresh(route)
    return route


def copy(session: Session, route: Route, name: str) -> Route:
    """A second route of the same owner from the same file (deliberately no
    duplicate check), in the same folder, the same way round - to change one
    without the other. Garmin courses and "shared by" stay with the original."""
    now = now_utc()
    twin = Route(**route.model_dump(exclude=_NOT_COPIED | {"name"}), name=name.strip()[:200],
                 sports=list(route.sports), uid=str(uuid.uuid4()), folder_id=route.folder_id,
                 created_at=now, updated_at=now, created_by_uid=route.created_by_uid,
                 created_by_username=route.created_by_username,
                 created_by_name=route.created_by_name)
    session.add(twin)
    session.commit()
    session.refresh(twin)
    return twin


def _apply_file(route: Route, data: bytes, track: gpx.Track) -> None:
    route.gpx_sha = store.put(data)
    for k, v in gpx.stats(track).items():
        setattr(route, k, v)


def create(session: Session, data: bytes, *, filename: str = "", name: str = "",
           description: str = "", sport_keys: list[str] = (), user: dict | None = None,
           source: str = "upload", source_url: str = "", external_id: str = "",
           folder_id: int | None = None) -> Route:
    """A new route of `user` from GPX bytes. Name and description fall back to
    the file's own (then the file name). The same file twice among the user's
    routes is a Duplicate."""
    track = gpx.parse(data)      # raises GpxError before anything is stored
    mine = owned_by(user)        # a duplicate is one among the user's own routes
    existing = session.exec(select(Route).where(*mine, Route.gpx_sha == store_sha(data))).first()
    if not existing and external_id:     # the same tour/course again, maybe changed since
        existing = session.exec(select(Route).where(*mine, Route.source == source,
                                                    Route.external_id == external_id)).first()
    if existing:
        raise Duplicate(existing)
    stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0] if filename else ""
    user = user or {}
    created = now_utc()
    route = Route(uid=str(uuid.uuid4()), created_at=created, updated_at=created,
                  name=(name or track.name or stem or "Route").strip()[:200],
                  description=(description or track.description).strip(),
                  sports=sports.clean(list(sport_keys)), gpx_sha="", distance_m=0,
                  start_lat=0, start_lon=0, min_lat=0, min_lon=0, max_lat=0, max_lon=0,
                  point_count=0, source=source, source_url=source_url, external_id=external_id,
                  folder_id=folder_id,
                  created_by_uid=user.get("uid"), created_by_username=user.get("username") or "",
                  created_by_name=user.get("display_name") or user.get("username") or "")
    _apply_file(route, data, track)
    session.add(route)
    session.commit()
    session.refresh(route)
    return route


def update(session: Session, route: Route, *, name: str, description: str,
           sport_keys: list[str], data: bytes | None = None,
           folder_id: int | None = None) -> Route:
    old_sha = route.gpx_sha
    if data:
        track = gpx.parse(data)
        dup = session.exec(select(Route).where(
            *_owner_is(route.created_by_uid, route.created_by_username),
            Route.gpx_sha == store_sha(data), Route.id != route.id)).first()
        if dup:
            raise Duplicate(dup)
        route.reversed = False           # a new file goes the way it is drawn
        _apply_file(route, data, track)
    route.name = name.strip()[:200] or route.name
    route.description = description.strip()
    route.sports = sports.clean(sport_keys)
    route.folder_id = folder_id
    route.updated_at = now_utc()
    session.add(route)
    session.commit()
    if data and old_sha != route.gpx_sha:
        _drop_file_if_unused(session, old_sha)
    return route


def delete(session: Session, route: Route) -> None:
    sha = route.gpx_sha
    session.delete(route)
    session.commit()
    _drop_file_if_unused(session, sha)


def _drop_file_if_unused(session: Session, sha: str) -> None:
    if not session.exec(select(Route).where(Route.gpx_sha == sha)).first():
        store.remove(sha)


_NOT_COPIED = {"id", "uid", "folder_id", "sports", "created_by_uid", "created_by_username",
               "created_by_name", "created_at", "updated_at", "shared_by_uid",
               "shared_by_username", "shared_by_name", "shared_from", "shared_at"}


def share(session: Session, route: Route, to: dict, sender: dict | None) -> Route | None:
    """A copy of `route` for the user `to` ({uid, username, display_name}),
    in their default folder; None when they have it already (the same file,
    the same tour/course, or a copy of this route). The GPX file is not
    copied - the store holds it once by its SHA. The caller commits."""
    match = [Route.gpx_sha == route.gpx_sha, Route.shared_from == route.uid]
    if route.external_id:
        match.append((Route.source == route.source) & (Route.external_id == route.external_id))
    if session.exec(select(Route).where(*_owner_is(to["uid"], to["username"]),
                                        or_(*match))).first():
        return None
    sender = sender or {}
    now = now_utc()
    copy = Route(**route.model_dump(exclude=_NOT_COPIED), sports=list(route.sports),
                 uid=str(uuid.uuid4()), created_at=now, updated_at=now,
                 created_by_uid=to["uid"], created_by_username=to["username"],
                 created_by_name=to.get("display_name") or to["username"],
                 shared_by_uid=sender.get("uid"), shared_by_username=sender.get("username") or "",
                 shared_by_name=sender.get("display_name") or sender.get("username") or "",
                 shared_from=route.uid, shared_at=now)
    session.add(copy)
    return copy
