"""Heights of every route from the elevation model (v1.5.0, Michael 2026-11-01).

MGC works the heights out itself, whatever the route came from - an
upload, Komoot, a Garmin course or activity, a suggestion: the MyCommons
block `dem` (app/dem/ is a copy - never edit it here; `MyCommons/sync.sh
dem app`) gives the Copernicus GLO-30 height of every point, averaged over
±50 m; those heights go into the stored GPX file (`gpx.with_elevations` -
all else in the file stays), and ascent/descent come from them with a 4 m
hysteresis (`gpx._climb`). Calibrated in MyFITContainer against Strava.

`Route.elevation_source`: "dem" (done), "kept" (the model has nothing
there - the file's own heights stay) or "pending" (a tile could not be
loaded: the route keeps the file's heights for now, `catch_up` tries again).
Tiles are cached in MGC_DEM_DIR (1° each, up to ~30 MB; only the cell
number leaves the server). The duplicate check keeps using the file as it
came (`Route.original_sha`). Mock point of the tests: `_sampler()`.
"""

from __future__ import annotations

import asyncio
import logging

from sqlmodel import select

from . import gpx, store
from .config import get_settings
from .db import get_session
from .dem import DemSampler, DemUnavailable, terrain
from .models import Route, now_utc

log = logging.getLogger(__name__)

DEM, KEPT, PENDING = "dem", "kept", "pending"
CATCH_UP_EVERY_S = 6 * 3600


def _sampler():
    return DemSampler(str(get_settings().dem_dir))


def correct(data: bytes) -> tuple[bytes, str]:
    """The file with the model's heights, and how it went (DEM / KEPT /
    PENDING - then the file as it came). Blocking (tile downloads): call it
    from a thread."""
    track = gpx.parse(data)
    try:
        heights = terrain.smoothed([(p[0], p[1]) for p in track.points], _sampler())
    except DemUnavailable as exc:
        log.warning("dem: %s", exc)
        return data, PENDING
    if heights is None:
        return data, KEPT
    return gpx.with_elevations(data, heights), DEM


def catch_up() -> int:
    """Every route still "pending" (made while a tile could not be loaded,
    or before v1.5.0) gets the model's heights now; routes sharing a file
    (copies, shared ones) are done together. Stops at the first tile it
    cannot load. Returns how many files were done."""
    from . import routes
    done = 0
    with get_session() as s:
        shas = list(dict.fromkeys(r.gpx_sha for r in s.exec(
            select(Route).where(Route.elevation_source == PENDING))))
    for sha in shas:
        try:
            data = store.get(sha)
        except OSError:
            continue
        try:
            new, how = correct(data)
        except Exception:                  # one odd file must not hold up all others
            log.exception("dem: file %s", sha[:12])
            new, how = data, KEPT
        if how == PENDING:
            break
        with get_session() as s:
            rows = s.exec(select(Route).where(Route.gpx_sha == sha,
                                              Route.elevation_source == PENDING)).all()
            new_sha = store.put(new) if how == DEM else sha
            for r in rows:
                r.gpx_sha, r.elevation_source, r.updated_at = new_sha, how, now_utc()
                for k, v in gpx.stats(routes.track_of(r)).items():
                    setattr(r, k, v)
                s.add(r)
            s.commit()
            if new_sha != sha:
                routes._drop_file_if_unused(s, sha)
        done += 1
    if done:
        log.info("dem: heights of %d files from the elevation model", done)
    return done


async def catch_up_loop() -> None:
    """At start and every CATCH_UP_EVERY_S, in a thread."""
    while True:
        try:
            await asyncio.to_thread(catch_up)
        except Exception:                      # never let the loop die
            log.exception("dem catch-up")
        await asyncio.sleep(CATCH_UP_EVERY_S)
