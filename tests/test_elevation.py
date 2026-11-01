"""Heights from the elevation model (elevation.py, dem block) with a fake
sampler - no tile is ever loaded."""

import pytest
from sqlmodel import select

from app import elevation, gpx, routes, store
from app.db import get_session
from app.dem import DemUnavailable
from app.models import Route
from tests.conftest import USER, make_gpx


class Slope:
    """The terrain rises 1 m per 0.0001° north (~11 m): a 20-point track
    heading north climbs ~19 m - whatever heights the file says."""
    def elevation(self, lat, lon):
        return 400 + (lat - 48.0) * 10_000


class Down:
    def elevation(self, lat, lon):
        raise DemUnavailable("tile N48_E011: network down")


class Sea:
    def elevation(self, lat, lon):
        return None


@pytest.fixture
def dem(monkeypatch):
    def use(sampler):
        monkeypatch.setattr(elevation, "_sampler", sampler)
    return use


def new(name="Hill", lon=11.0, user=USER, n=200, step=0.0001):
    with get_session() as s:
        return routes.create(s, make_gpx(name, lon=lon, n=n, step=step), sport_keys=["cycling"],
                             user=user)


def heights(route):
    return [p[2] for p in gpx.parse(store.get(route.gpx_sha)).points]


def test_the_model_heights_go_into_the_file(dem):
    dem(Slope)
    route = new()                 # the file says 500, 501, ... - the model 400 + ~1 m per point
    assert route.elevation_source == "dem"
    h = heights(route)
    assert 400 <= h[0] < 410 and h == sorted(h)
    assert route.min_ele < 410 and 180 <= route.ascent_m <= 200 and route.descent_m == 0
    assert route.original_sha == routes.store_sha(make_gpx("Hill", n=200, step=0.0001))
    assert route.gpx_sha != route.original_sha


def test_the_same_file_again_is_still_a_duplicate(dem):
    dem(Slope)
    first = new()
    with pytest.raises(routes.Duplicate) as d:
        new()
    assert d.value.route.id == first.id


def test_everything_else_in_the_file_stays():
    data = (b'<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1" '
            b'xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">'
            b'<wpt lat="48.5" lon="11.5"><name>Hut</name></wpt><trk><name>T</name><trkseg>'
            b'<trkpt lat="48.0" lon="11.0"><time>2026-11-01T08:00:00Z</time><extensions>'
            b'<gpxtpx:TrackPointExtension><gpxtpx:hr>120</gpxtpx:hr></gpxtpx:TrackPointExtension>'
            b'</extensions></trkpt><trkpt lat="0" lon="0"><ele>1</ele></trkpt>'
            b'<trkpt lat="48.01" lon="11.0"><ele>9</ele></trkpt></trkseg></trk></gpx>')
    out = gpx.with_elevations(data, [500, 510])
    assert [p[2] for p in gpx.parse(out).points] == [500.0, 510.0]
    for kept in (b"<name>Hut</name>", b"<time>2026-11-01T08:00:00Z</time>",
                 b"<gpxtpx:hr>120</gpxtpx:hr>", b'lat="0" lon="0"><ele>1</ele>'):
        assert kept in out                # the (0,0) point is not the track's: left alone
    assert out.index(b"<ele>500.0</ele>") < out.index(b"<time>")
    with pytest.raises(ValueError):
        gpx.with_elevations(data, [1])


def test_at_sea_the_file_keeps_its_heights(dem):
    dem(Sea)
    route = new()
    assert route.elevation_source == "kept" and heights(route)[0] == 500


def test_no_tile_now_the_catch_up_does_it_later(dem):
    dem(Down)
    route = new()
    with get_session() as s:
        copy = routes.copy(s, s.get(Route, route.id), "Hill (copy)")
        turned = routes.turn_round(s, s.get(Route, copy.id))
    assert route.elevation_source == "pending" and heights(route)[0] == 500   # as it came
    old_sha = route.gpx_sha
    assert elevation.catch_up() == 0                     # still down: nothing, no harm
    dem(Slope)
    assert elevation.catch_up() == 1                     # one file for both routes
    with get_session() as s:
        a, b = s.get(Route, route.id), s.get(Route, turned.id)
    assert a.elevation_source == b.elevation_source == "dem" and a.gpx_sha == b.gpx_sha
    assert heights(a)[0] < 410 and a.ascent_m >= 180
    assert b.reversed and b.descent_m == a.ascent_m      # the turned one: figures backwards
    assert not store._path(old_sha).exists()             # the old file went
    assert elevation.catch_up() == 0                     # nothing left


def test_reverse_and_download_use_the_model_heights(dem, client):
    dem(Slope)
    with get_session() as s:
        route = routes.create(s, make_gpx("Hill", n=200, step=0.0001), sport_keys=["cycling"])
    data = client.get(f"/routes/{route.id}/gpx").content
    assert gpx.parse(data).points[0][2] < 410


def test_an_old_database_gets_the_columns(tmp_path, monkeypatch):
    import sqlite3

    from app import db
    new()
    path = db.get_engine().url.database
    db.get_engine().dispose()
    con = sqlite3.connect(path)
    con.execute("DROP INDEX IF EXISTS ix_route_original_sha")
    for col in ("elevation_source", "original_sha"):
        con.execute(f"ALTER TABLE route DROP COLUMN {col}")
    con.commit()
    con.close()
    monkeypatch.setattr(db, "_engine", None)
    with get_session() as s:
        r = s.exec(select(Route)).one()
    assert r.elevation_source == "pending" and r.original_sha == r.gpx_sha
