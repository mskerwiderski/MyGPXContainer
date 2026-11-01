"""Tables. Routes and folders belong to one user (Michael 2026-10-29): the
`created_by_*` fields are the owner, kept by MyAuth uid AND username (a
rebuilt MyAuth may hand out an uid again). Sharing a route gives the other
user a copy of their own."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Folder(SQLModel, table=True):
    """A user's own, like their routes: each of their routes is in exactly one.
    The default folder is no row - a route with folder_id None is in it."""
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    created_by_uid: int | None = None
    created_by_username: str = ""
    created_at: datetime = Field(default_factory=now_utc)


class Route(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    uid: str = Field(index=True, unique=True)          # stable (uuid4), for Garmin marks and links
    name: str
    description: str = ""
    sports: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    gpx_sha: str = Field(index=True)
    folder_id: int | None = Field(default=None, index=True)   # None = the default folder
    # derived from the GPX (gpx.stats)
    distance_m: float
    ascent_m: int | None = None
    descent_m: int | None = None
    min_ele: int | None = None
    max_ele: int | None = None
    start_lat: float
    start_lon: float
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float
    loop: bool = False
    point_count: int
    # ridden the other way round than the file goes (v1.1.0): the file stays
    # byte-identical, map, profile, figures, download and Garmin are reversed
    reversed: bool = False
    # where it came from: upload | komoot | garmin | url
    source: str = "upload"
    source_url: str = ""
    external_id: str = ""
    created_by_uid: int | None = None     # the owner (for a shared copy: who got it)
    created_by_username: str = ""
    created_by_name: str = ""
    created_at: datetime = Field(default_factory=now_utc)   # UTC
    updated_at: datetime = Field(default_factory=now_utc)
    # a copy someone shared: who, and the uid of their route (it may change
    # or go since - the copy is the receiver's own)
    shared_by_uid: int | None = None
    shared_by_username: str = ""
    shared_by_name: str = ""
    shared_from: str = ""
    shared_at: datetime | None = None


class GarminCourse(SQLModel, table=True):
    """A course this app made in a user's OWN Garmin Connect from one of their
    routes - sent on request, never on its own (v0.17.0, Michael 2026-10-31).
    The row outlives the route (no FK on purpose): a deleted route's course
    stays in Garmin Connect until the user removes it on "My Garmin"."""
    id: int | None = Field(default=None, primary_key=True)
    uid: int = Field(index=True)          # MyAuth uid ...
    username: str                        # ... and username (uids can come back)
    route_uid: str = Field(index=True)
    name: str = ""                       # the route's name when sent (shown once it is gone)
    activity_type: str                   # Garmin typeKey (sports.py)
    course_id: int | None = None
    synced_hash: str = ""                # route state the course was built from
    synced_at: datetime | None = None
    error: str = ""                      # the last thing that went wrong with this course
    # devices (Garmin deviceIds) the CURRENT course was sent to, and those that
    # still hold an older one (a changed route gets a new course)
    pushed_to: list[int] = Field(default_factory=list, sa_column=Column(JSON, nullable=False,
                                                                        server_default="[]"))
    pushed_old: list[int] = Field(default_factory=list, sa_column=Column(JSON, nullable=False,
                                                                         server_default="[]"))


class RoutingRegion(SQLModel, table=True):
    """A map region the loop suggestions cover (a Geofabrik extract), added by
    an app admin. routing.py writes the list for the routing container."""
    id: int | None = Field(default=None, primary_key=True)
    geofabrik_id: str = Field(index=True, unique=True)
    name: str
    pbf: str
    added_by_uid: int | None = None
    added_by_username: str = ""
    added_at: datetime = Field(default_factory=now_utc)


class GarminPrefs(SQLModel, table=True):
    """Per user: their course-capable Garmin devices, as last seen."""
    id: int | None = Field(default=None, primary_key=True)
    uid: int = Field(index=True)
    username: str
    devices: list[dict] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))


class Account(SQLModel, table=True):
    """A person in modes `local` and `single` (app/auth/local.py) - in mode
    `myauth` MyAuth has the people and this table stays empty. `id` is their
    uid everywhere else (routes, folders, Garmin rows)."""
    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)      # lower case
    display_name: str = ""
    password_hash: str = ""          # empty while the invitation is open
    is_admin: bool = False
    active: bool = True
    language: str = ""               # "" = the browser's
    timezone: str = ""               # "" = the app's (MGC_TIMEZONE)
    invite_hash: str = ""            # sha256 of the one-time link's token
    invite_expires: datetime | None = None
    created_at: datetime = Field(default_factory=now_utc)


class AccountSession(SQLModel, table=True):
    """A browser signed in to an Account; the cookie holds the token, the
    table only its sha256."""
    id: int | None = Field(default=None, primary_key=True)
    token_hash: str = Field(index=True, unique=True)
    account_id: int = Field(index=True)
    created_at: datetime = Field(default_factory=now_utc)
    expires_at: datetime


class GarminLink(SQLModel, table=True):
    """An own account's connection to Garmin Connect (modes local and single,
    app/auth/garmin_link.py) - in mode myauth MyAuth holds it. The tokens are
    encrypted (Fernet); the password was used once and is stored nowhere."""
    id: int | None = Field(default=None, primary_key=True)
    uid: int = Field(index=True, unique=True)
    garmin_name: str = ""                # the Garmin account's name, as Garmin says
    oauth1: str = ""                     # encrypted JSON, lasts about a year
    oauth2: str = ""                     # encrypted JSON, renewed when due
    connected_at: datetime = Field(default_factory=now_utc)
    error: str = ""                      # the last renewal that failed


class WayInfo(SQLModel, table=True):
    """Way types and surfaces of a GPX file (waytypes.py) as GraphHopper
    matched it, per profile (bike / foot) - or why it could not. Kept per
    file, not per route: copies and shared routes ask once."""
    id: int | None = Field(default=None, primary_key=True)
    gpx_sha: str = Field(index=True)
    profile: str
    data: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    error: str = ""
    made_at: datetime = Field(default_factory=now_utc)
