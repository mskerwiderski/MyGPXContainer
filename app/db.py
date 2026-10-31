"""Engine + session factory. SQLite under DATA_DIR."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        settings.ensure_dirs()
        _engine = create_engine(f"sqlite:///{settings.data_dir / 'mygpxcontainer.db'}",
                                connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(_engine, "connect")
        def _pragmas(con, _):
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA foreign_keys=ON")

        from . import models  # noqa: F401 - registers the tables
        SQLModel.metadata.create_all(_engine)
        _migrate(_engine)
    return _engine


def _migrate(engine: Engine) -> None:
    """Changes create_all doesn't make to an existing DB."""
    with engine.begin() as con:
        cols = [r[1] for r in con.exec_driver_sql("PRAGMA table_info(route)")]
        if "folder_id" not in cols:      # v0.8.0: folders
            con.exec_driver_sql("ALTER TABLE route ADD COLUMN folder_id INTEGER")
            con.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_route_folder_id ON route (folder_id)")
        cols = [r[1] for r in con.exec_driver_sql("PRAGMA table_info(garmincourse)")]
        if "pushed_to" not in cols:      # v0.9.0: courses sent on to devices
            con.exec_driver_sql("ALTER TABLE garmincourse ADD COLUMN pushed_to JSON NOT NULL DEFAULT '[]'")
        cols = [r[1] for r in con.exec_driver_sql("PRAGMA table_info(garminprefs)")]
        if "push" in cols:               # v0.9.1: devices only on request, no auto push
            con.exec_driver_sql("ALTER TABLE garminprefs DROP COLUMN push")
        cols = [r[1] for r in con.exec_driver_sql("PRAGMA table_info(route)")]
        if "shared_from" not in cols:    # v0.11.0: routes per user, shared as copies
            for col, kind in (("shared_by_uid", "INTEGER"),
                              ("shared_by_username", "VARCHAR NOT NULL DEFAULT ''"),
                              ("shared_by_name", "VARCHAR NOT NULL DEFAULT ''"),
                              ("shared_from", "VARCHAR NOT NULL DEFAULT ''"),
                              ("shared_at", "DATETIME")):
                con.exec_driver_sql(f"ALTER TABLE route ADD COLUMN {col} {kind}")
            _split_by_owner(con)
        cols = [r[1] for r in con.exec_driver_sql("PRAGMA table_info(garmincourse)")]
        if "wanted" in cols:             # v0.17.0: sent on request, no more marks and sync
            _rows_are_courses(con, cols)


def _rows_are_courses(con, cols: list[str]) -> None:
    """v0.17.0, once (Michael 2026-10-31): a row was the WISH to have a route
    in Garmin, a sync brought the account to it; now a row is a course that
    is there. Marks that never made it to Garmin go; unmarked rows whose
    course still exists stay - the user removes them on "My Garmin". The
    name comes from the route (a deleted one's from Garmin, on the next visit
    of "My Garmin")."""
    con.exec_driver_sql("DELETE FROM garmincourse WHERE course_id IS NULL")
    if "name" not in cols:
        con.exec_driver_sql("ALTER TABLE garmincourse ADD COLUMN name VARCHAR NOT NULL DEFAULT ''")
        con.exec_driver_sql("UPDATE garmincourse SET name = COALESCE((SELECT route.name FROM route "
                            "WHERE route.uid = garmincourse.route_uid), '')")
    if "pushed_old" not in cols:
        con.exec_driver_sql("ALTER TABLE garmincourse ADD COLUMN pushed_old JSON NOT NULL "
                            "DEFAULT '[]'")
    con.exec_driver_sql("ALTER TABLE garmincourse DROP COLUMN wanted")


def _split_by_owner(con) -> None:
    """v0.11.0, once (Michael 2026-10-29): until then every user saw every
    route and folder, now each has their own. Whoever has someone else's route
    in their Garmin gets a copy of it (in their default folder, shared by its
    owner) and their row points to the copy - the course in Garmin stays as
    it is. A route in someone else's folder moves to a folder of the same name
    of its owner. Plain SQL over whatever columns the table has."""
    def owner(row) -> tuple:
        return row.get("created_by_uid"), row.get("created_by_username") or ""

    routes = [dict(r) for r in con.exec_driver_sql("SELECT * FROM route").mappings()]
    by_uid = {r["uid"]: r for r in routes}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
    gcols = [r[1] for r in con.exec_driver_sql("PRAGMA table_info(garmincourse)")]
    picks = con.exec_driver_sql("SELECT id, uid, username, route_uid FROM garmincourse"
                                + (" WHERE wanted = 1" if "wanted" in gcols else "")
                                ).mappings().all()
    for g in picks:
        r = by_uid.get(g["route_uid"])
        who = (g["uid"], g["username"])
        if r is None or owner(r) == who:
            continue
        theirs = [x for x in routes if owner(x) == who]
        copy = next((x for x in theirs if x.get("shared_from") == r["uid"]
                     or x.get("gpx_sha") == r.get("gpx_sha")), None)
        if copy is None:
            copy = {k: v for k, v in r.items() if k != "id"}
            copy.update(uid=str(uuid.uuid4()), folder_id=None,
                        created_by_uid=g["uid"], created_by_username=g["username"],
                        created_by_name=next((x["created_by_name"] for x in theirs
                                              if x.get("created_by_name")), g["username"]),
                        shared_by_uid=r.get("created_by_uid"),
                        shared_by_username=r.get("created_by_username") or "",
                        shared_by_name=r.get("created_by_name") or r.get("created_by_username") or "",
                        shared_from=r["uid"], shared_at=now)
            names = ", ".join(copy)
            con.exec_driver_sql(f"INSERT INTO route ({names}) VALUES ({', '.join('?' * len(copy))})",
                                tuple(copy.values()))
            routes.append(copy)
        con.exec_driver_sql("UPDATE garmincourse SET route_uid = ? WHERE id = ?",
                            (copy["uid"], g["id"]))

    folders = [dict(f) for f in con.exec_driver_sql(
        "SELECT id, name, created_by_uid, created_by_username FROM folder").mappings()]
    by_id = {f["id"]: f for f in folders}
    for r in routes:
        f = by_id.get(r.get("folder_id"))
        if f is None or owner(f) == owner(r):
            continue
        same = next((x for x in folders if owner(x) == owner(r)
                     and x["name"].casefold() == f["name"].casefold()), None)
        if same is None:
            uid, username = owner(r)
            new_id = con.exec_driver_sql(
                "INSERT INTO folder (name, created_by_uid, created_by_username, created_at) "
                "VALUES (?, ?, ?, ?)", (f["name"], uid, username, now)).lastrowid
            same = {"id": new_id, "name": f["name"], "created_by_uid": uid,
                    "created_by_username": username}
            folders.append(same)
            by_id[new_id] = same
        con.exec_driver_sql("UPDATE route SET folder_id = ? WHERE uid = ?", (same["id"], r["uid"]))


def get_session() -> Session:
    return Session(get_engine(), expire_on_commit=False)
