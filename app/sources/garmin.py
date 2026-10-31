"""Garmin Connect courses (connect.garmin.com/modern/course/<id>), read with
the SIGNED-IN user's Garmin token: their own courses and public ones.
GPX from course-service/course/gpx/<id>, name, description and sport from
course-service/course/<id> (both tried live 2026-10-27), through
`garmin_courses.Client` (MyCommons block `garmin_api`)."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from ..auth import GarminUnavailable, garmin_token
from ..garmin_courses import Client, GarminError
from ..i18n import N_
from ..sports import SPORTS
from . import Fetched, SourceError

NOT_SHARED = N_("Garmin does not share this course with you. Only your own "
                "and public courses can be added.")


async def fetch(url: str, uid: int | None) -> Fetched:
    m = re.search(r"/course/(\d+)", urlsplit(url).path)
    if not m:
        raise SourceError(N_("This Garmin Connect link does not point to a course."))
    course_id = m.group(1)
    try:
        token = await garmin_token(uid)
    except GarminUnavailable as e:
        raise SourceError(e.text) from e
    garmin = Client(token)
    try:
        j = await garmin.course(course_id)
        if j is None:
            raise SourceError(NOT_SHARED)
        data = await garmin.gpx(course_id)
    except GarminError as exc:
        if exc.status in (401, 403):
            raise SourceError(NOT_SHARED) from exc
        if exc.status is None:              # not reachable
            raise SourceError(N_("{source} is not reachable right now."),
                              source="Garmin Connect") from exc
        raise SourceError(N_("{source} answered with an error ({status})."),
                          source="Garmin Connect", status=exc.status) from exc
    type_id = j.get("activityTypePk")
    sport = [s.key for s in SPORTS if s.type_id == type_id][:1]
    return Fetched(data=data, source="garmin", source_url=url, external_id=course_id,
                   name=(j.get("courseName") or "").strip(),
                   description=(j.get("description") or "").strip(), sports=sport)
