"""Stops on the way for the suggestions (v1.3.0), against the fake GraphHopper
of test_suggest (it draws straight lines through the points it gets)."""

import asyncio
import math
from urllib.parse import urlencode

from sqlmodel import select

from app import gpx, places, suggest
from app.db import get_session
from app.models import Route
from tests.test_suggest import START, gh  # noqa: F401 - the fixture

ALLING = (48.15, 11.30)
GRAFRATH = (48.19, 11.25)


def stop(p, label):
    return f"{p[0]},{p[1]},{label}"


def page(client, **params):
    via = params.pop("via", [])
    q = urlencode({"sport": "cycling", "profile": "flat", "lat": START[0], "lon": START[1],
                   "place": "", **params}) + "".join("&" + urlencode({"via": v}) for v in via)
    return client.get("/suggest?" + q)


def test_one_stop_gives_a_loop_out_one_way_back_another():
    (there,), (back,) = suggest.shaping_points(START, [ALLING], 0.3, "m")
    mid = ((START[0] + ALLING[0]) / 2, (START[1] + ALLING[1]) / 2)
    # the two shaping points lie on opposite sides of the line start-stop
    def side(p):
        return ((ALLING[1] - START[1]) * (p[0] - START[0])
                - (ALLING[0] - START[0]) * (p[1] - START[1]))
    assert side(there) * side(back) < 0
    assert gpx.haversine(there, mid) > 500 and gpx.haversine(back, mid) > 500


def test_more_stops_push_outward():
    stops = [ALLING, GRAFRATH]
    pts = suggest.shaping_points(START, stops, 0.3, "m")
    cx = (START[0] + ALLING[0] + GRAFRATH[0]) / 3
    cy = (START[1] + ALLING[1] + GRAFRATH[1]) / 3
    for (a, b), (p,) in zip(suggest._legs(START, stops), pts):
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        assert gpx.haversine(p, (cx, cy)) > gpx.haversine(mid, (cx, cy))   # farther out


def test_a_wide_loop_bends_in_a_bow():
    legs = suggest.shaping_points(START, [ALLING], 1.0, "m")
    assert [len(leg) for leg in legs] == [3, 3]
    ring = suggest._ring(START, [ALLING], 1.0, "m")
    assert len(ring) == 9 and ring[0] == ring[-1] == START and ring[4] == ALLING


def test_the_width_follows_the_wished_distance():
    w20, shortest = suggest.loop_width(START, [ALLING], 20)
    w40, _ = suggest.loop_width(START, [ALLING], 40)
    assert w40 > w20 >= suggest.MIN_WIDTH and shortest < 20
    est = suggest._crow_km(START, [ALLING], w40) * suggest.DETOUR
    assert abs(est - 40) < 0.5
    w, shortest = suggest.loop_width(START, [ALLING], 1)          # too short for the stop
    assert w == suggest.MIN_WIDTH and shortest > 1


def test_loop_over_stops_in_order(client, gh):  # noqa: F811
    r = page(client, kind="loop", km=30, via=[stop(ALLING, "Alling"), stop(GRAFRATH, "Grafrath")])
    assert r.status_code == 200 and "suggest-card" in r.text
    body = gh.bodies[0]
    assert "algorithm" not in body
    pts = [(p[1], p[0]) for p in body["points"]]
    # start, shape, Alling, shape, Grafrath, shape, start
    assert len(pts) == 7 and pts[0] == pts[-1] == START
    assert pts[2] == ALLING and pts[4] == GRAFRATH
    keys = {b.get("points")[1][0] for b in gh.bodies}
    assert len(keys) > 1                                            # shapes vary
    assert 'name="via" value="48.15,11.3,Alling"' in r.text        # kept in the form and cards
    assert 'name="cand" value="L' in r.text


def test_a_too_short_distance_says_so(client, gh):  # noqa: F811
    r = page(client, kind="loop", km=5, via=[stop((48.40, 11.60), "Far")])
    assert "Over these stops a loop is at least about" in r.text


def test_oneway_through_the_stops(client, gh):  # noqa: F811
    finish = (48.30, 11.50)
    r = page(client, kind="oneway", to_lat=finish[0], to_lon=finish[1], to_place="Dachau",
             via=[stop(ALLING, "Alling")])
    assert r.status_code == 200 and "suggest-card" in r.text
    straight = [b for b in gh.bodies if len(b["points"]) == 3]
    assert straight and [(p[1], p[0]) for p in straight[0]["points"]] == [START, ALLING, finish]
    assert any(len(b["points"]) == 4 for b in gh.bodies)          # the "w" ones over a point beside
    assert not any(b.get("algorithm") == "alternative_route" for b in gh.bodies)


def test_a_typed_stop_is_looked_up(client, gh, monkeypatch):  # noqa: F811
    async def search(text, lang, near):
        return [{"label": "Alling, Bayern", "lat": ALLING[0], "lon": ALLING[1]}] if text == "Alling" else []
    monkeypatch.setattr(places, "search", search)
    r = page(client, kind="loop", km=30, via=[",,Alling"])
    assert "suggest-card" in r.text and 'value="48.15,11.3,Alling, Bayern"' in r.text
    r = page(client, kind="loop", km=30, via=[",,Nowhere"])
    assert "Place “Nowhere” not found" in r.text


def test_take_over_computes_the_same_loop(client, gh, monkeypatch):  # noqa: F811
    monkeypatch.setattr(places, "route_head", lambda points, oneway, stops=None: None)
    r = page(client, kind="loop", km=30, via=[stop(ALLING, "Alling"), stop(GRAFRATH, "Grafrath")])
    import re
    cand = re.search(r'name="cand" value="(L[^"]+)"', r.text).group(1)
    n = len(gh.bodies)
    r = client.post("/suggest/take", data={
        "kind": "loop", "sport": "cycling", "profile": "flat", "lat": START[0], "lon": START[1],
        "km": 30, "heading": 0, "cand": cand, "start_label": "Starnberg",
        "via": [stop(ALLING, "Alling"), stop(GRAFRATH, "Grafrath")]}, follow_redirects=False)
    assert r.status_code == 303
    assert gh.bodies[n]["points"] == next(b["points"] for b in gh.bodies[:n]
                                          if b["points"][1] == gh.bodies[n]["points"][1])
    with get_session() as s:
        route = s.exec(select(Route)).one()
    assert route.name.startswith("Starnberg via Alling, Grafrath ")
    bad = client.post("/suggest/take", data={
        "kind": "loop", "sport": "cycling", "profile": "flat", "lat": START[0], "lon": START[1],
        "km": 30, "cand": "Lm:99", "via": [stop(ALLING, "Alling")]})
    assert bad.status_code == 422


def test_names_from_the_place_list_with_stops(monkeypatch):
    names = {ALLING: "Alling", GRAFRATH: "Grafrath", START: "Puchheim"}

    def locality(lat, lon):
        return min(names.items(), key=lambda kv: math.dist(kv[0], (lat, lon)))[1]
    monkeypatch.setattr(places, "locality", locality)
    monkeypatch.setattr(places, "suburb", lambda lat, lon: None)
    pts = [(*START, None), (*ALLING, None), (*START, None)]
    assert places.route_head(pts, False, [ALLING, GRAFRATH]) == "Puchheim via Alling, Grafrath"
    assert places.route_head(pts, False) == "Puchheim via Alling"


def test_where_names_a_tapped_point(client, monkeypatch):
    monkeypatch.setattr(places, "suburb", lambda lat, lon: "Puchheim-Ort")
    monkeypatch.setattr(places, "_locality", lambda lat, lon: [48.15, 11.3, "village", "Alling"])
    assert client.get("/suggest/where?lat=48.15&lon=11.3").json() == {
        "label": "Alling", "lat": 48.15, "lon": 11.3}            # no suburb outside cities
    monkeypatch.setattr(places, "suburb", lambda lat, lon: "Altstadt")
    monkeypatch.setattr(places, "_locality", lambda lat, lon: [48.1, 11.5, "city", "München"])
    assert client.get("/suggest/where?lat=48.15&lon=11.3").json()["label"] == "Altstadt, München"
    monkeypatch.setattr(places, "_locality", lambda lat, lon: None)
    assert client.get("/suggest/where?lat=48.15&lon=11.3").json()["label"] == "48.15000, 11.30000"
    assert client.get("/suggest/where?lat=x").json() == {"label": ""}


def test_too_many_stops(client, gh):  # noqa: F811
    r = page(client, kind="loop", km=30, via=[stop(ALLING, "A")] * (suggest.STOPS_MAX + 1))
    assert "At most 50 stops." in r.text and gh.bodies == []


def test_no_stops_stays_as_before(gh):  # noqa: F811
    loops = asyncio.run(suggest.suggest("cycling", START, 30, "flat"))
    assert loops and all(b.get("algorithm") == "round_trip" for b in gh.bodies)


def test_one_map_for_start_stops_and_destination(client):
    loop = client.get("/suggest").text
    assert 'data-pick-map' in loop and 'name="pick" value="start" form="pick-none"' in loop
    # the destination choice is there only for A to B
    assert 'data-kind-only="oneway" hidden><input type="radio" name="pick" value="finish"' in loop
    oneway = client.get("/suggest?kind=oneway").text
    assert 'data-kind-only="oneway" ><input type="radio" name="pick" value="finish"' in oneway
    # every stop can become start or destination, and goes with one tap on ×
    stops = client.get("/suggest?via=48.15,11.3,Alling").text
    assert 'data-stop-as="start"' in stops and 'data-stop-as="finish"' in stops
    assert 'class="stop-remove' in stops
