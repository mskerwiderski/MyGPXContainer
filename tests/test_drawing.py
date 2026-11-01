"""Editing a route's way (drawing.py, v1.6.0): roads from a fake GraphHopper
(suggest._route), heights from a fake elevation model - nothing leaves."""

import json

import pytest

from app import elevation, gpx, routes, store, suggest
from app.db import get_session
from app.models import Route
from tests.conftest import USER, make_gpx
from tests.test_suggest import FakeGH

BEN = {**USER, "uid": 8, "username": "ben", "display_name": "Ben"}


class Slope:
    def elevation(self, lat, lon):
        return 400 + (lat - 48.0) * 10_000


@pytest.fixture
def gh(monkeypatch):
    fake = FakeGH()
    monkeypatch.setattr(suggest, "_route", fake.route)
    return fake


def new(name="Hill", sports=("road_biking",), user=None):
    with get_session() as s:
        return routes.create(s, make_gpx(name, n=50), sport_keys=list(sports), user=user)


def points(route_id):
    with get_session() as s:
        return [(p[0], p[1]) for p in routes.track_of(s.get(Route, route_id)).points]


def test_the_page_has_the_points_the_way_the_route_goes(client):
    route = new()
    with get_session() as s:
        routes.turn_round(s, s.get(Route, route.id))
    page = client.get(f"/routes/{route.id}/draw").text
    data = json.loads(page.split('id="draw-data">')[1].split("</script>")[0])
    assert data["points"][0] == [48.049, 11.0] and len(data["points"]) == 50   # turned: north first
    assert data["routing"] is False
    assert "Edit the way" in client.get(f"/routes/{route.id}").text


def test_a_leg_over_roads(client, gh):
    route = new(sports=("trail_running",))
    r = client.post(f"/routes/{route.id}/draw/leg",
                    json={"points": [[48.0, 11.0], [48.01, 11.02], [48.02, 11.0]]})
    assert r.status_code == 200
    way = r.json()["points"]
    assert len(way) > 3 and way[0] == pytest.approx([48.0, 11.0], abs=1e-4)
    body = gh.bodies[-1]
    engine = suggest.ENGINE["trail_running"]
    assert body["profile"] == engine and body["points"][1] == [11.02, 48.01]   # lon, lat
    assert "algorithm" not in body
    assert body["custom_model"]["priority"] == suggest.RULES.get(engine, [])


def test_no_way_and_no_service(client, gh):
    route = new()
    asked = {"points": [[48.0, 11.0], [48.02, 11.0]]}
    gh.mode = "none"
    r = client.post(f"/routes/{route.id}/draw/leg", json=asked)
    assert r.status_code == 404 and "straight line" in r.json()["problem"]
    gh.mode = "down"
    assert client.post(f"/routes/{route.id}/draw/leg", json=asked).status_code == 503


@pytest.mark.parametrize("asked", [
    {"points": [[48.0, 11.0]]},                           # one point is no way
    {"points": [[48.0, 11.0]] * 11},                      # a leg takes at most 10
    {"points": [[95.0, 11.0], [48.0, 11.0]]},             # no latitude
    {"points": [["x", 11.0], [48.0, 11.0]]},
    {"nothing": 1},
])
def test_bad_points_are_refused(client, gh, asked):
    route = new()
    assert client.post(f"/routes/{route.id}/draw/leg", json=asked).status_code == 422
    assert not gh.bodies


def test_the_preview_has_the_models_heights(client, monkeypatch):
    monkeypatch.setattr(elevation, "_sampler", Slope)
    route = new()
    line = [[48.0 + i * 0.0002, 11.0] for i in range(100)]
    f = client.post(f"/routes/{route.id}/draw/preview", json={"points": line}).json()
    assert 2.1 < f["km"] < 2.3 and f["up"] > 150 and f["down"] == 0 and f["loop"] is False
    assert len(f["profile"]["km"]) == len(f["profile"]["ele"]) > 10


def test_the_preview_without_the_model(client):
    route = new()
    f = client.post(f"/routes/{route.id}/draw/preview",
                    json={"points": [[48.0, 11.0], [48.01, 11.0]]}).json()
    assert f["km"] == pytest.approx(1.11, abs=0.01) and f["profile"] is None


def test_saving_changes_the_route(client, monkeypatch):
    monkeypatch.setattr(elevation, "_sampler", Slope)
    route = new()
    line = [[48.0, 11.0], [48.01, 11.0], [48.01, 11.01]]
    r = client.post(f"/routes/{route.id}/draw", data={"points": json.dumps(line)},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/routes/{route.id}?drawn=1"
    with get_session() as s:
        saved = s.get(Route, route.id)
    assert points(route.id) == [tuple(p) for p in line]
    assert saved.name == "Hill" and saved.sports == ["road_biking"] and saved.gpx_sha != route.gpx_sha
    assert saved.elevation_source == "dem" and saved.ascent_m > 50
    assert gpx.parse(store.get(saved.gpx_sha)).points[0][2] == pytest.approx(400, abs=5)
    assert "The new way is saved" in client.get(r.headers["location"]).text


def test_saving_a_turned_route_keeps_the_drawn_direction(client):
    route = new()
    with get_session() as s:
        routes.turn_round(s, s.get(Route, route.id))
    line = [[48.05, 11.0], [48.0, 11.0]]
    client.post(f"/routes/{route.id}/draw", data={"points": json.dumps(line)})
    assert points(route.id) == [tuple(p) for p in line]


def test_saving_as_a_copy_leaves_the_original(client):
    route = new()
    before = points(route.id)
    line = [[48.0, 11.0], [48.02, 11.0]]
    r = client.post(f"/routes/{route.id}/draw", data={"points": json.dumps(line), "as_copy": "1"},
                    follow_redirects=False)
    copy_id = int(r.headers["location"].split("/routes/")[1].split("?")[0])
    assert copy_id != route.id and r.headers["location"].endswith("?copied=1")
    assert points(route.id) == before and points(copy_id) == [tuple(p) for p in line]
    with get_session() as s:
        copy = s.get(Route, copy_id)
    assert copy.name == "Hill (copy)" and copy.sports == ["road_biking"]


def test_unreadable_points_change_nothing(client):
    route = new()
    r = client.post(f"/routes/{route.id}/draw", data={"points": "[[48, 11]"})
    assert r.status_code == 422 and points(route.id) == points(route.id)
    with get_session() as s:
        assert s.get(Route, route.id).gpx_sha == route.gpx_sha


def test_only_the_owner(client, myauth, gh):
    route = new(user=USER)
    myauth.body = dict(BEN)
    client.cookies.set("sso_session", "s-ben")
    line = json.dumps([[48.0, 11.0], [48.02, 11.0]])
    assert client.get(f"/routes/{route.id}/draw").status_code == 404
    assert client.post(f"/routes/{route.id}/draw/leg",
                       json={"points": [[48.0, 11.0], [48.02, 11.0]]}).status_code == 404
    assert client.post(f"/routes/{route.id}/draw/preview",
                       json={"points": [[48.0, 11.0], [48.02, 11.0]]}).status_code == 404
    assert client.post(f"/routes/{route.id}/draw", data={"points": line}).status_code == 404
    with get_session() as s:
        assert s.get(Route, route.id).gpx_sha == route.gpx_sha
    assert not gh.bodies
