"""A user's routes in their own Garmin Connect - only what they ask for.

Since v0.17.0 (Michael 2026-10-31) nothing happens on its own: the user sends
routes (one or several, each as a sport they pick) to Garmin Connect and, if
they like, on to some or all of their devices; on "My Garmin" they see what
is there and remove courses again. A row (`GarminCourse`) is a course that
is in Garmin Connect. Deleting a route leaves its course alone; a changed
route shows as changed until it is sent again (which replaces the course); a
course deleted in Garmin Connect drops out of the list when "My Garmin" next
looks (`refresh`) and is not made again. Everything runs for the signed-in
user only, with their token.

Only courses this app made are deleted: their description carries
`MGC:route=<route uid>`, read per course (the list has no descriptions).
Any route uid counts: since routes are per user (v0.11.0) a row may point
to the user's copy while the course still carries the original's uid.
Devices go one way: Garmin can put a course on a device, but neither update
nor remove it there.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, field

from sqlmodel import Session, select

from . import routes, store
from .auth import GarminUnavailable, garmin_token
from .db import get_session
from .garmin_courses import Client, GarminError
from .i18n import N_
from .models import GarminCourse, GarminPrefs, Route, now_utc
from .sports import BY_KEY

log = logging.getLogger(__name__)


MARK = "MGC:route="


def mark(route_uid: str) -> str:
    return MARK + route_uid


def route_of(session: Session, user: dict, route_uid: str) -> Route | None:
    """The user's own route with this uid (None: gone, or not theirs)."""
    return session.exec(select(Route).where(*routes.owned_by(user),
                                            Route.uid == route_uid)).first()


def route_hash(route: Route, activity_type: str) -> str:
    raw = json.dumps([route.gpx_sha, route.name, route.description, activity_type])
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def course_url(course_id: int) -> str:
    return f"https://connect.garmin.com/modern/course/{course_id}"


# ---------- the user's courses ----------

def rows_of(session: Session, user: dict) -> list[GarminCourse]:
    return list(session.exec(select(GarminCourse).where(
        GarminCourse.uid == user["uid"], GarminCourse.username == user["username"])))


def row_for(session: Session, user: dict, route_uid: str) -> GarminCourse | None:
    return session.exec(select(GarminCourse).where(
        GarminCourse.uid == user["uid"], GarminCourse.username == user["username"],
        GarminCourse.route_uid == route_uid)).first()


def state(row: GarminCourse, route: Route | None) -> str:
    """deleted (the route is gone) | changed (since it was sent) | current"""
    if route is None:
        return "deleted"
    if row.synced_hash != route_hash(route, row.activity_type):
        return "changed"
    return "current"


# ---------- devices ----------

def prefs_of(session: Session, user: dict) -> GarminPrefs:
    p = session.exec(select(GarminPrefs).where(GarminPrefs.uid == user["uid"],
                                               GarminPrefs.username == user["username"])).first()
    return p or GarminPrefs(uid=user["uid"], username=user["username"])


def remember_devices(session: Session, prefs: GarminPrefs, devices: list[dict]) -> None:
    prefs.devices = devices
    session.add(prefs)
    session.commit()


def device_names(prefs: GarminPrefs, ids: list[int]) -> list[str]:
    names = {d["id"]: d["name"] for d in prefs.devices}
    return [names.get(i, str(i)) for i in ids]


def on_devices(prefs: GarminPrefs, row: GarminCourse) -> list[tuple[str, bool]]:
    """(device name, holds an older version) for every device the route went to."""
    return ([(n, False) for n in device_names(prefs, row.pushed_to)]
            + [(n, True) for n in device_names(prefs, row.pushed_old)])


# ---------- sending, removing, looking ----------

async def send(uid: int, username: str, items: list[tuple[str, str]],
               device_ids: list[int]) -> dict:
    """Puts routes into the user's Garmin Connect - (route uid, sport) each -
    and then on the devices asked for. A route already there as it is now
    keeps its course; a changed one (or another sport) gets a new course, and
    the devices that had the old one keep it (`pushed_old`)."""
    result = {"kind": "send", "routes": 0, "devices": [], "failed": []}
    client = Client(await garmin_token(uid))   # GarminUnavailable goes to the caller
    owned = await client.owned()
    user = {"uid": uid, "username": username}
    sent_to: set[int] = set()
    with get_session() as s:
        prefs = prefs_of(s, user)
        for route_uid, activity_type in items:
            route = route_of(s, user, route_uid)
            if route is None:
                continue
            row = row_for(s, user, route_uid) or GarminCourse(
                uid=uid, username=username, route_uid=route_uid, activity_type=activity_type)
            try:
                await _course(client, owned, row, route, activity_type)
                s.add(row)
                s.commit()
                result["routes"] += 1
                for device in device_ids:
                    await client.push(row.course_id, route.name, device)
                    if device not in row.pushed_to:
                        row.pushed_to = [*row.pushed_to, device]
                    row.pushed_old = [d for d in row.pushed_old if d != device]
                    sent_to.add(device)
                row.error = ""
            except GarminError as e:
                log.warning("garmin send uid=%s route=%s: %s", uid, route_uid, e)
                row.error = str(e)
                result["failed"].append((route.name, str(e)))
            if row.course_id:
                s.add(row)
            s.commit()
        result["devices"] = device_names(prefs, [d for d in device_ids if d in sent_to])
    return result


async def _course(client: Client, owned: dict, row: GarminCourse, route: Route,
                  activity_type: str) -> None:
    """The route's course in Garmin Connect as the route is now."""
    h = route_hash(route, activity_type)
    exists = bool(row.course_id) and row.course_id in owned
    if exists and row.synced_hash == h:
        row.name = route.name
        return
    if exists:
        await _remove_own(client, owned, row)
    description = (route.description[:1000] + "\n\n" if route.description else "") + mark(route.uid)
    row.course_id = await client.create(data=store.get(route.gpx_sha), name=route.name,
                                        description=description,
                                        type_id=BY_KEY[activity_type].type_id)
    row.name, row.activity_type, row.synced_hash, row.synced_at = (
        route.name, activity_type, h, now_utc())
    row.pushed_old = list(dict.fromkeys([*row.pushed_old, *row.pushed_to]))
    row.pushed_to = []


async def _remove_own(client: Client, owned: dict[int, dict], row: GarminCourse) -> bool:
    """Deletes the row's course if Garmin still has it with our mark. False:
    it is there, but without the mark (the user changed it in Garmin)."""
    if not row.course_id or row.course_id not in owned:
        return True
    if MARK not in (await client.description(row.course_id) or ""):
        return False
    await client.delete(row.course_id)
    return True


async def remove(uid: int, username: str, row_ids: list[int]) -> dict:
    """Removes the user's courses (their rows by id) from Garmin Connect."""
    result = {"kind": "remove", "removed": 0, "failed": []}
    client = Client(await garmin_token(uid))
    owned = await client.owned()
    user = {"uid": uid, "username": username}
    with get_session() as s:
        for row in rows_of(s, user):
            if row.id not in row_ids:
                continue
            try:
                if not await _remove_own(client, owned, row):
                    result["failed"].append((row.name, N_(
                        "Changed in Garmin Connect, so it was left there - delete it there.")))
                s.delete(row)
                result["removed"] += 1
            except GarminError as e:
                log.warning("garmin remove uid=%s course=%s: %s", uid, row.course_id, e)
                row.error = str(e)
                s.add(row)
                result["failed"].append((row.name, str(e)))
            s.commit()
    return result


async def refresh(uid: int, username: str) -> None:
    """What Garmin Connect has now: rows whose course is gone there (deleted
    by the user in Garmin) drop out, names of deleted routes are filled in
    from Garmin, and the device list is brought up to date. Raises
    GarminUnavailable / GarminError - the page then shows what it knew."""
    user = {"uid": uid, "username": username}
    with get_session() as s:
        before = {r.id: r.course_id for r in rows_of(s, user)}
    client = Client(await garmin_token(uid))
    owned = await client.owned()
    try:
        devices = await client.devices()
    except GarminError as e:
        log.warning("garmin devices uid=%s: %s", uid, e)
        devices = None
    with get_session() as s:
        if devices is not None:
            remember_devices(s, prefs_of(s, user), devices)
        for row in rows_of(s, user):
            # only rows as they were before asking: a send running meanwhile may
            # have made a course the list did not have yet
            if row.id in before and row.course_id == before[row.id] \
                    and row.course_id not in owned:
                s.delete(row)
            elif not row.name and row.course_id in owned:
                row.name = owned[row.course_id].get("courseName") or ""
                s.add(row)
        s.commit()


# ---------- running it in the background ----------

@dataclass
class Run:
    running: bool = False
    jobs: list = field(default_factory=list)   # ("send", items, devices) | ("remove", ids)
    error: str = ""               # English key or Garmin's text
    result: dict = field(default_factory=dict)  # of the last job (send / remove)
    finished_at: object = None


_runs: dict[int, Run] = {}
_tasks: set[asyncio.Task] = set()


def run_state(uid: int) -> Run:
    return _runs.get(uid) or Run()


def start_send(uid: int, username: str, items: list[tuple[str, str]],
               device_ids: list[int]) -> None:
    """`send` in the background (one run per user; jobs queue up)."""
    _enqueue(uid, username, ("send", tuple(items), tuple(device_ids)))


def start_remove(uid: int, username: str, row_ids: list[int]) -> None:
    _enqueue(uid, username, ("remove", tuple(row_ids)))


def _enqueue(uid: int, username: str, job: tuple) -> None:
    run = _runs.setdefault(uid, Run())
    if job not in run.jobs:
        run.jobs.append(job)
    if run.running:
        return
    run.running, run.error = True, ""
    task = asyncio.create_task(_loop(uid, username, run))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _loop(uid: int, username: str, run: Run) -> None:
    try:
        while run.jobs:
            job = run.jobs.pop(0)
            run.result = {}
            try:
                if job[0] == "send":
                    run.result = await send(uid, username, list(job[1]), list(job[2]))
                else:
                    run.result = await remove(uid, username, list(job[1]))
                run.error = ""
            except GarminUnavailable as e:
                run.error = e.text
            except GarminError as e:
                run.error = str(e)
            except Exception:        # never leave the run marked as running
                log.exception("garmin %s uid=%s", job[0], uid)
                run.error = N_("Something went wrong with Garmin Connect.")
    finally:
        run.running, run.finished_at = False, now_utc()
