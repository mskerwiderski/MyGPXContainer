"""Garmin Connect course API with ONE user's token (from MyAuth).

The requests themselves go through the MyCommons block `garmin_api`
(`app/garmin_api/` is a copy - never edit it here); this module keeps what is
MyGPXContainer's own: the course built like Michael's own ones, our
elevations, the retries while Garmin is "not yet ready", the errors for the
row and the device list.

Endpoints as tried live 2026-10-27 (MFC session "Gravel 90"):
- POST course-service/course/import (multipart `file`) parses a GPX and
  saves nothing; its geoPoints come back WITHOUT elevation - we fill them in
  from our own track, interpolated over the distance.
- POST course-service/course saves it (activityTypePk, rulePK 2 = private,
  WGS84, elevationSource 3 like the courses Michael made in Garmin itself).
- GET course-service/course/owner/<displayName> lists the user's courses -
  WITHOUT their description (live: courseDescription null); that comes
  only with GET course-service/course/<id>.
- DELETE course-service/course/<id> removes one (404 = already gone).
- Devices: GET device-service/deviceregistration/devices (`courseCapable`,
  `deviceCategories` - the Edge says DEDICATED_BIKE_COMPUTER). A course goes
  to a device as a device message (POST device-service/devicemessage/
  messages, like "Send to device" in Garmin Connect) pointing at
  course-service/course/fit/<course>/<device>?elevation=true - the device
  fetches it on its next sync. There is no message that REMOVES a course
  from a device. Right
  after it was made Garmin answers 429 "not yet ready to delete or update"
  for a moment (live) - `delete` waits and tries again a few times.
`_client(token)` is the mock point of the tests.
"""

from __future__ import annotations

import asyncio
import bisect
import math
import re
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx

from . import gpx
from .garmin_api import client as garmin_api

DELETE_TRIES, DELETE_WAIT_S = 5, 5
TIMEOUT_S = 60                  # a long GPX takes Garmin's import a while
_sleep = asyncio.sleep          # mock point: tests don't wait


class GarminError(Exception):
    """The text goes onto the row; `status` is Garmin's HTTP status, None
    when Garmin was not reachable or answered without one."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _client(token: str) -> garmin_api.GarminClient:
    """The block's client with the user's token as MyAuth handed it out -
    never asked again, as before one token serves a whole sync run."""
    client = garmin_api.GarminClient(timeout=TIMEOUT_S)
    client.oauth2_token = garmin_api.OAuth2Token(token, "", 0, math.inf)
    return client


class Client:
    def __init__(self, token: str):
        self.token = token

    @asynccontextmanager
    async def _garmin(self) -> AsyncIterator[garmin_api.GarminClient]:
        client = _client(self.token)
        try:
            yield client
        except httpx.HTTPError as exc:
            raise GarminError(
                f"Garmin Connect is not reachable ({exc.__class__.__name__})") from exc
        except garmin_api.GarminError as exc:
            raise GarminError(f"Garmin Connect: {exc}", getattr(exc, "status", None)) from exc
        finally:
            await client.aclose()

    async def owned(self) -> dict[int, dict]:
        """The user's courses by id."""
        async with self._garmin() as g:
            return {c["courseId"]: c for c in await g.list_courses() if c.get("courseId")}

    async def course(self, course_id: int | str) -> dict | None:
        """A course (own or public), None if it is gone."""
        async with self._garmin() as g:
            return await g.get_course(course_id)

    async def activities(self, start: int = 0, limit: int = 30, activity_type: str | None = None,
                         start_date: str | None = None, end_date: str | None = None) -> list[dict]:
        """The user's activities, newest first, a page at a time."""
        async with self._garmin() as g:
            return await g.list_activities(start, limit, activity_type, start_date, end_date)

    async def activity(self, activity_id: int | str) -> dict | None:
        """An activity (own or public), None if it is gone; GarminError 401/403
        when it is someone else's and not public."""
        async with self._garmin() as g:
            try:
                return await g.get_activity_detail(int(activity_id))
            except garmin_api.GarminError as exc:
                # the block says the status only in its text ("… HTTP 403")
                if "not found" in str(exc):
                    return None
                status = re.search(r"HTTP (\d+)", str(exc))
                raise GarminError(f"Garmin Connect: {exc}",
                                  int(status.group(1)) if status else None) from exc

    async def activity_gpx(self, activity_id: int | str) -> bytes:
        async with self._garmin() as g:
            return await g.activity_gpx(activity_id)

    async def gpx(self, course_id: int | str) -> bytes:
        async with self._garmin() as g:
            return await g.course_gpx(course_id)

    async def description(self, course_id: int) -> str | None:
        """The course's description, None if it is gone."""
        course = await self.course(course_id)
        return None if course is None else course.get("description") or ""

    async def devices(self) -> list[dict]:
        """The user's course-capable devices: {id, name, bike_computer}."""
        async with self._garmin() as g:
            found = await g.list_devices()
        return [{"id": d["deviceId"], "name": d.get("productDisplayName") or d.get("displayName")
                 or str(d["deviceId"]),
                 "bike_computer": "DEDICATED_BIKE_COMPUTER" in (d.get("deviceCategories") or [])}
                for d in found if d.get("courseCapable") and d.get("deviceId")]

    async def push(self, course_id: int, name: str, device_id: int) -> None:
        """Queues the course for the device ("Send to device")."""
        async with self._garmin() as g:
            await g.send_course(course_id, device_id, name)

    async def delete(self, course_id: int) -> None:
        for attempt in range(DELETE_TRIES):
            try:
                async with self._garmin() as g:
                    await g.delete_course(course_id)
                return
            except GarminError as e:
                if e.status != 429:
                    raise
            if attempt < DELETE_TRIES - 1:
                await _sleep(DELETE_WAIT_S)
        raise GarminError("Garmin Connect is still processing this course; "
                          "the next sync tries again", 429)

    async def create(self, *, data: bytes, name: str, description: str, type_id: int) -> int:
        async with self._garmin() as g:
            course = await g.import_course(data)
        points = course.get("geoPoints") or []
        if len(points) < 2:
            raise GarminError("Garmin Connect could not read the GPX file")
        track = gpx.parse(data)
        _fill_elevation(points, track)
        st = gpx.stats(track)
        lats = [p["latitude"] for p in points]
        lons = [p["longitude"] for p in points]
        course.update({
            "courseName": name[:255], "description": description,
            "activityTypePk": type_id, "rulePK": 2, "sourceTypeId": 3,
            "coordinateSystem": "WGS84", "targetCoordinateSystem": "WGS84",
            "originalCoordinateSystem": "WGS84", "elevationSource": 3,
            "distanceMeter": round(points[-1].get("distance") or st["distance_m"], 2),
            "elevationGainMeter": st["ascent_m"], "elevationLossMeter": st["descent_m"],
            "startPoint": dict(points[0]),
            "boundingBox": {"center": None,
                            "lowerLeft": {"latitude": min(lats), "longitude": min(lons)},
                            "upperRight": {"latitude": max(lats), "longitude": max(lons)},
                            "lowerLeftLatIsSet": True, "lowerLeftLongIsSet": True,
                            "upperRightLatIsSet": True, "upperRightLongIsSet": True},
        })
        async with self._garmin() as g:
            return await g.save_course(course)


def _fill_elevation(points: list[dict], track: gpx.Track) -> None:
    """Garmin's import drops the heights: take ours, linear over the
    distance (Garmin's distances scaled onto ours)."""
    pts = [p for p in track.points if p[2] is not None]
    if len(pts) < 2:
        return
    dist = gpx.distances(pts)
    total = points[-1].get("distance") or dist[-1]
    for p in points:
        if p.get("elevation") is not None:
            continue
        d = (p.get("distance") or 0.0) * dist[-1] / total
        i = min(max(bisect.bisect_left(dist, d), 1), len(dist) - 1)
        t = (d - dist[i - 1]) / ((dist[i] - dist[i - 1]) or 1.0)
        p["elevation"] = round(pts[i - 1][2] + t * (pts[i][2] - pts[i - 1][2]), 2)
