"""Which way a route goes, turning it round, copying it (v1.1.0)."""

import asyncio
import re

from sqlmodel import select

from app import gpx, routes, store
from app.db import get_session
from app.models import GarminCourse, Route
from tests.conftest import USER, make_gpx


def new_route(name="Hill", n=20, user=USER):
    """Heading north and climbing: 500 m at the start, 519 m at the end. The
    pages without sign-in see the routes without an owner (user=None)."""
    with get_session() as s:
        return routes.create(s, make_gpx(name, n=n), sport_keys=["cycling"], user=user)


def reload(route):
    with get_session() as s:
        return s.get(Route, route.id)


def test_sketch_arrows_point_the_way():
    north = gpx.Track(points=[(48.0 + i * 0.001, 11.0, None) for i in range(20)])
    sk = gpx.sketch(north)
    assert len(sk["arrows"]) == 3 and all(a["a"] == -90 for a in sk["arrows"])   # up the page
    south = gpx.sketch(gpx.reverse(north))
    assert all(a["a"] == 90 for a in south["arrows"])
    square = [(48.0, 11.0, None), (48.0, 11.01, None), (47.99, 11.01, None),
              (47.99, 11.0, None), (48.0, 11.0, None)]       # east, south, west, north
    assert gpx.sketch(gpx.Track(points=square))["clockwise"]
    assert not gpx.sketch(gpx.Track(points=square[::-1]))["clockwise"]


def test_turning_round_swaps_start_and_climbs_but_keeps_the_file():
    route = new_route()
    original = store.get(route.gpx_sha)
    start, up, down = (route.start_lat, route.start_lon), route.ascent_m, route.descent_m
    with get_session() as s:
        r = routes.turn_round(s, s.get(Route, route.id))
        assert r.reversed and (r.ascent_m, r.descent_m) == (down, up)
        assert (r.start_lat, r.start_lon) != start and r.distance_m == route.distance_m
        assert r.gpx_sha == route.gpx_sha and store.get(r.gpx_sha) == original   # byte-identical
        pts = gpx.parse(routes.gpx_bytes(r)).points
        assert pts[0][0] > pts[-1][0]                       # the download goes south now
        assert routes.track_of(r).points[0][:2] == pts[0][:2]
        routes.turn_round(s, r)
        assert not r.reversed and (r.start_lat, r.start_lon) == start
        assert routes.gpx_bytes(r) == original


def test_reverse_from_the_page(client):
    route = new_route(user=None)
    page = client.get(f"/routes/{route.id}").text
    assert "as recorded" in page and "Reverse direction" in page
    first = re.search(r'id="track">(.*?)</script>', page, re.S).group(1)
    r = client.post(f"/routes/{route.id}/reverse", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/routes/{route.id}"
    page = client.get(f"/routes/{route.id}").text
    assert "<strong>reversed</strong>" in page
    assert re.search(r'id="track">(.*?)</script>', page, re.S).group(1) != first
    assert "sketch-arrow" in client.get("/").text
    gpx_file = client.get(f"/routes/{route.id}/gpx").content
    assert gpx.parse(gpx_file).points[0][0] > gpx.parse(gpx_file).points[-1][0]


def test_a_new_file_goes_the_way_it_is_drawn():
    route = new_route()
    with get_session() as s:
        r = routes.turn_round(s, s.get(Route, route.id))
        routes.update(s, r, name="Hill", description="", sport_keys=["cycling"],
                      data=make_gpx("Other", lon=12.0))
        assert not r.reversed


def test_garmin_gets_the_route_the_way_it_goes(garmin):
    from app import garmin_sync
    route = new_route()

    def send():
        asyncio.run(garmin_sync.send(7, "anna", [(route.uid, "cycling")], []))

    send()
    with get_session() as s:
        row = s.exec(select(GarminCourse)).one()
        assert garmin_sync.state(row, s.get(Route, route.id)) == "current"
        routes.turn_round(s, s.get(Route, route.id))
        assert garmin_sync.state(row, s.get(Route, route.id)) == "changed"
    send()
    (_, course), = garmin.accounts["tok7"].items()
    lats = [p["latitude"] for p in course["geoPoints"]]
    assert lats[0] > lats[-1]                               # south: the other way round


def test_copy_from_the_page(client):
    route = new_route(user=None)
    r = client.post(f"/routes/{route.id}/copy", follow_redirects=False)
    assert r.status_code == 303
    twin_id = int(re.search(r"/routes/(\d+)\?copied=1", r.headers["location"]).group(1))
    page = client.get(r.headers["location"]).text
    assert "Hill (copy)" in page and "This is a copy" in page
    with get_session() as s:
        twin, orig = s.get(Route, twin_id), s.get(Route, route.id)
        assert twin.uid != orig.uid and twin.gpx_sha == orig.gpx_sha
        assert (twin.created_by_uid, twin.folder_id, twin.sports) == (
            orig.created_by_uid, orig.folder_id, orig.sports)
    client.post(f"/routes/{twin_id}/reverse")               # change one, not the other
    assert not reload(route).reversed and reload(Route(id=twin_id)).reversed
    client.post(f"/routes/{route.id}/delete")                # the file stays for the copy
    with get_session() as s:
        assert store.get(s.get(Route, twin_id).gpx_sha)


def test_copy_in_german(client, myauth):
    myauth.body = {**USER, "language": "de"}
    client.cookies.set("sso_session", "x")
    route = new_route()
    location = client.post(f"/routes/{route.id}/copy", follow_redirects=False).headers["location"]
    assert "Hill (Kopie)" in client.get(location).text


def test_someone_elses_route_cannot_be_turned_or_copied(client, myauth):
    route = new_route()
    myauth.body = {**USER, "uid": 8, "username": "ben"}
    client.cookies.set("sso_session", "ben")
    assert client.post(f"/routes/{route.id}/reverse").status_code == 404
    assert client.post(f"/routes/{route.id}/copy").status_code == 404
    assert not reload(route).reversed
    with get_session() as s:
        assert len(s.exec(select(Route)).all()) == 1


def test_migration_adds_the_column(tmp_path, monkeypatch):
    import sqlite3

    from app import db
    new_route()
    path = db.get_engine().url.database
    db.get_engine().dispose()
    con = sqlite3.connect(path)
    con.execute("ALTER TABLE route DROP COLUMN reversed")
    con.commit()
    con.close()
    monkeypatch.setattr(db, "_engine", None)
    with get_session() as s:
        assert s.exec(select(Route)).one().reversed is False
