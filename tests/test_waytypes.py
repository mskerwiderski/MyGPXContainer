"""Way types and surfaces (waytypes.py) against a fake GraphHopper /match."""

import asyncio
from datetime import timedelta

import pytest
from sqlmodel import select

from app import config, routes, waytypes
from app.db import get_session
from app.models import Route, WayInfo
from tests.conftest import make_gpx

# 4 matched points heading east, ~744 m apart
COORDS = [[11.0, 48.0], [11.01, 48.0], [11.02, 48.0], [11.03, 48.0]]
ANSWER = {"paths": [{"points": {"coordinates": COORDS}, "details": {
    "road_class": [[0, 1, "cycleway"], [1, 2, "residential"], [2, 3, "cycleway"]],
    "surface": [[0, 2, "asphalt"], [2, 3, "missing"]],
    "track_type": [[2, 3, "grade2"]]}}]}


@pytest.fixture
def gh(monkeypatch):
    """A routing service: answers /match with `gh.answer` (status, JSON)."""
    monkeypatch.setenv("MGC_ROUTING_URL", "http://routing:8989")
    monkeypatch.setattr(config, "_settings", None)

    class Fake:
        answer = (200, ANSWER)
        calls: list = []

    Fake.calls = []

    async def match(body, profile):
        Fake.calls.append(profile)
        return Fake.answer
    monkeypatch.setattr(waytypes, "_match", match)
    return Fake


def new_route(sports=("cycling",)):
    with get_session() as s:
        return routes.create(s, make_gpx("Ride"), sport_keys=list(sports))


def test_summary_merges_and_fills_surface_from_the_track_grade():
    d = waytypes.from_match(ANSWER)
    assert [e["key"] for e in d["way"]] == ["cycleway", "minor"]      # the fixed order
    cyc = d["way"][0]
    assert cyc["parts"] == [[0.0, 0.33333], [0.66667, 1.0]] and round(cyc["share"], 2) == 0.67
    assert [e["key"] for e in d["surface"]] == ["asphalt", "gravel"]   # grade2 -> gravel
    assert d["surface"][0]["parts"] == [[0.0, 0.66667]]                 # merged
    assert abs(sum(e["m"] for e in d["way"]) - d["m"]) <= 1


def test_no_routing_service_no_panel(client):
    route = new_route()
    assert "Way types and surfaces" not in client.get(f"/routes/{route.id}").text


def test_the_page_asks_after_it_shows_and_keeps_the_answer(client, gh):
    route = new_route()
    page = client.get(f"/routes/{route.id}").text
    assert f'data-ways-url="/routes/{route.id}?ways=1"' in page and gh.calls == []
    page = client.get(f"/routes/{route.id}?ways=1").text
    assert gh.calls == ["bike"]
    assert "Cycleway" in page and "Minor road" in page and "Gravel surface" in page
    assert 'class="ways-seg series-1"' in page and 'id="ways-data"' in page
    page = client.get(f"/routes/{route.id}").text                   # kept: no second ask
    assert "data-ways-url" not in page and "Cycleway" in page and gh.calls == ["bike"]


def test_kept_per_file_and_read_backwards_when_turned_round(gh):
    route = new_route()
    forward = asyncio.run(waytypes.for_route(route))
    with get_session() as s:
        r = routes.turn_round(s, s.get(Route, route.id))
        back = asyncio.run(waytypes.for_route(r))
        twin = routes.copy(s, r, "Twin")
    assert gh.calls == ["bike"]                                      # one ask for all three
    assert back["way"][1]["parts"] == [[0.33333, 0.66667]]
    assert back["surface"][0]["parts"] == [[0.33333, 1.0]]          # asphalt now at the end
    assert forward["surface"][0]["parts"] == [[0.0, 0.66667]]
    assert asyncio.run(waytypes.for_route(twin)) == back


def test_on_foot_is_matched_as_foot(gh):
    asyncio.run(waytypes.for_route(new_route(sports=("running",))))
    assert gh.calls == ["foot"]


def test_outside_the_map_is_kept_and_asked_again_after_a_day(client, gh):
    route = new_route()
    gh.answer = (400, {"message": "Sequence is broken for submitted track"})
    page = client.get(f"/routes/{route.id}?ways=1").text
    assert "outside the map regions" in page
    assert "outside the map regions" in client.get(f"/routes/{route.id}").text
    assert len(gh.calls) == 1
    with get_session() as s:
        row = s.exec(select(WayInfo)).one()
        row.made_at = row.made_at - timedelta(seconds=waytypes.RETRY_S + 1)
        s.add(row)
        s.commit()
    gh.answer = (200, ANSWER)
    assert "data-ways-url" in client.get(f"/routes/{route.id}").text   # due again
    assert "Cycleway" in client.get(f"/routes/{route.id}?ways=1").text


def test_a_server_error_is_not_kept(client, gh):
    route = new_route()
    gh.answer = (503, {})
    assert "not reachable right now" in client.get(f"/routes/{route.id}?ways=1").text
    with get_session() as s:
        assert s.exec(select(WayInfo)).all() == []


def test_reversing_swaps_the_panel_too(client, gh):
    route = new_route()
    client.get(f"/routes/{route.id}?ways=1")
    page = client.get(f"/routes/{route.id}").text
    assert 'data-swap="route-direction,route-sports,route-stats,track,ways,garmin-card"' in page


def test_a_tiny_share_reads_less_than_one_percent(client, gh):
    coords = [[11.0 + i * 0.001, 48.0] for i in range(301)]
    gh.answer = (200, {"paths": [{"points": {"coordinates": coords}, "details": {
        "road_class": [[0, 1, "cycleway"], [1, 300, "track"]], "surface": [], "track_type": []}}]})
    route = new_route()
    page = client.get(f"/routes/{route.id}?ways=1").text
    assert "&lt; 1 %" in page and ">0 %<" not in page
