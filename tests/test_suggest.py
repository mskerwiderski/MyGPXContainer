"""Loop suggestions against a fake GraphHopper (suggest._route): circles
around the start in the asked heading, the climb and the ground depending on
the heading, so the scoring has something to choose from."""

import asyncio
import json
import math
import re

import pytest
from sqlmodel import select

from app import config, places, suggest
from app.db import get_session
from app.models import Route
from tests.conftest import USER

START = (48.17, 11.35)


def circle(start, km, heading, n=80):
    """A loop of about `km` through `start`, its middle in direction `heading`."""
    r = km * 1000 / (2 * math.pi)
    h = math.radians(heading)
    cx, cy = r * math.sin(h), r * math.cos(h)          # metres east/north of the start
    k_lat, k_lon = 1 / 111_320, 1 / (111_320 * math.cos(math.radians(start[0])))
    out = []
    for i in range(n + 1):
        a = h + math.pi + 2 * math.pi * i / n
        x, y = cx + r * math.sin(a), cy + r * math.cos(a)
        out.append((start[0] + y * k_lat, start[1] + x * k_lon))
    return out


class FakeGH:
    """`climb[heading]` metres up and down over the loop, `length[heading]`
    the length factor; headings 0-150 on tracks/gravel, the others on a
    secondary road."""

    def __init__(self):
        self.bodies = []
        self.mode = "ok"
        self.climb = {h: 100 + h for h in suggest.HEADINGS}
        self.length = {h: 1.0 + (h % 90) / 900 for h in suggest.HEADINGS}

    async def route(self, body):
        self.bodies.append(body)
        if self.mode == "nomap":
            return 400, {"message": "Cannot find point 0: 10.0,20.0"}
        if self.mode == "down":
            raise suggest.Unavailable("Suggestions are not available right now. "
                                      "Please try again in a minute.")
        if self.mode == "none":
            return 400, {"message": "Connection between locations not found"}
        if body.get("algorithm") != "round_trip":
            return 200, {"paths": self.oneway(body)}
        lon, lat = body["points"][0]
        h = body["headings"][0]
        km = body["round_trip.distance"] / 1000 * self.length[h]
        pts = circle((lat, lon), km, h)
        n = len(pts)
        coords = [[p[1], p[0], 500 + self.climb[h] / 2 * (1 - math.cos(2 * math.pi * i / (n - 1)))]
                  for i, p in enumerate(pts)]
        offroad = h < 180
        return 200, {"paths": [{
            "distance": km * 1000, "ascend": self.climb[h],
            "points": {"coordinates": coords},
            "details": {"surface": [[0, n - 1, "gravel" if offroad else "asphalt"]],
                        "road_class": [[0, n - 1, "track" if offroad else "secondary"]]}}]}


    def oneway(self, body):
        """A to B (over a via point when given): GraphHopper's own alternatives
        bulge a little to the side, the first on tracks."""
        way = [(p[1], p[0]) for p in body["points"]]
        n_alt = 2 if body.get("algorithm") == "alternative_route" else 1
        paths = []
        for k in range(n_alt):
            pts = []
            for (a, b) in zip(way, way[1:]):
                for i in range(30):
                    t = i / 30
                    pts.append((a[0] + (b[0] - a[0]) * t + math.sin(math.pi * t) * 0.01 * k,
                                a[1] + (b[1] - a[1]) * t))
            pts.append(way[-1])
            n = len(pts)
            coords = [[p[1], p[0], 500 + 40 * math.sin(i / 5)] for i, p in enumerate(pts)]
            paths.append({"distance": 0, "ascend": 0, "points": {"coordinates": coords},
                          "details": {"surface": [[0, n - 1, "gravel" if k == 0 else "asphalt"]],
                                      "road_class": [[0, n - 1, "track"]]}})
        return paths


@pytest.fixture
def gh(monkeypatch):
    fake = FakeGH()
    monkeypatch.setattr(suggest, "_route", fake.route)
    return fake


def run(coro):
    return asyncio.run(coro)


def test_request_carries_profile_wish_and_sport_rules():
    b = suggest.body("gravel_cycling", START, 50, "hilly", 120)
    assert b["profile"] == "gravel" and b["algorithm"] == "round_trip"
    assert b["points"] == [[11.35, 48.17]] and b["headings"] == [120]
    assert b["round_trip.distance"] == 50_000 and b["ch.disable"] is True
    rules = b["custom_model"]["priority"]
    assert rules[0] == suggest.WISH["hilly"][0] and rules[1:] == suggest.RULES["gravel"]
    assert suggest.body("hiking", START, 15, "flat", 0)["profile"] == "hike"
    assert suggest.body("road_biking", START, 80, "flat", 0)["profile"] == "racingbike"


def test_out_and_back_counts_as_run_twice():
    there = [(48.0 + i * 0.001, 11.0, None) for i in range(50)]
    # about half - the stretch just before the turn does not count
    assert 0.35 < suggest.repeat_share(there + there[::-1]) <= 0.5
    loop = [(p[0], p[1], None) for p in circle(START, 10, 0)]
    assert suggest.repeat_share(loop) < 0.05


def test_three_loops_going_different_ways(gh):
    loops = run(suggest.suggest("gravel_cycling", START, 40, "flat"))
    assert len(gh.bodies) == 12 and len(loops) == 3
    assert {b["headings"][0] for b in gh.bodies} == set(range(0, 360, 30))
    for a in loops:
        for b in loops:
            if a is not b:
                d = abs(a.bearing - b.bearing)
                assert min(d, 360 - d) >= 60
    assert loops[0].score <= loops[1].score <= loops[2].score
    assert all(lp.unpaved == 100 and lp.big_roads == 0 for lp in loops)   # gravel: off-road first
    assert abs(loops[0].km - 40) / 40 < 0.1 and loops[0].profile == "flat"


def test_profile_wish_decides(gh):
    gh.climb = {h: 50 if h != 210 else 900 for h in suggest.HEADINGS}
    best = run(suggest.suggest("road_biking", START, 40, "mountainous"))[0]
    assert best.heading == 210 and best.profile == "mountainous"
    loops = run(suggest.suggest("road_biking", START, 40, "hilly"))
    assert not suggest.fits(loops, "hilly")                # the terrain cannot


def test_on_foot_the_profile_limits_are_higher(gh):
    gh.climb = {h: 250 for h in suggest.HEADINGS}          # 25 m/km on 10 km
    assert run(suggest.suggest("hiking", START, 10, "hilly"))[0].profile == "hilly"
    assert run(suggest.suggest("gravel_cycling", START, 10, "hilly"))[0].profile == "mountainous"


def test_no_map_and_no_service(gh):
    gh.mode = "nomap"
    with pytest.raises(suggest.Unavailable, match="no map"):
        run(suggest.suggest("cycling", START, 30, "flat"))
    gh.mode = "down"
    with pytest.raises(suggest.Unavailable, match="not available"):
        run(suggest.suggest("cycling", START, 30, "flat"))
    gh.mode = "none"
    assert run(suggest.suggest("cycling", START, 30, "flat")) == []


def test_without_routing_url_suggestions_are_off():
    with pytest.raises(suggest.Unavailable, match="not set up"):
        run(suggest.suggest("cycling", START, 30, "flat"))


# ---------- the pages ----------

def login(client, myauth):
    myauth.body = dict(USER)
    client.cookies.set("sso_session", "s")


def test_form_alone(client, gh):
    page = client.get("/suggest").text
    assert 'id="suggest-form"' in page
    assert 'value="cycling" data-group="bike" data-limit="300" selected' in page
    assert 'value="running" data-group="run" data-limit="100"' in page
    assert "Routes up to 300 km" in page and 'max="300"' in page
    assert 'class="card suggest-card"' not in page and gh.bodies == []
    assert 'href="/suggest"' in client.get("/").text


def test_three_cards_and_the_map(client, gh):
    r = client.get("/suggest?sport=gravel_cycling&km=40&profile=flat&lat=48.17&lon=11.35")
    page = r.text
    assert r.status_code == 200 and page.count('class="card suggest-card"') == 3
    lines = json.loads(page.split('id="suggest-lines">')[1].split("</script>")[0])
    assert lines["start"] == [48.17, 11.35] and len(lines["loops"]) == 3
    assert "100 % unpaved" in page and 'name="heading"' in page


def test_problems_on_the_page(client, gh, monkeypatch):
    assert "Pick a start" in client.get("/suggest?sport=cycling&km=30&profile=flat").text
    assert "from 2 to 300 km" in client.get("/suggest?sport=cycling&km=900&lat=48&lon=11").text
    assert "Place “Nowhere” not found" in client.get("/suggest?sport=cycling&km=30&place=Nowhere").text
    gh.mode = "nomap"
    assert "no map for this area" in client.get("/suggest?sport=cycling&km=30&lat=10&lon=20").text
    gh.mode = "none"
    assert "No loop found from here" in client.get("/suggest?sport=cycling&km=30&lat=48&lon=11").text


def test_place_as_start(client, gh, monkeypatch):
    from app.geosearch import openmeteo

    async def lookup(name, lang="en"):
        return ("Starnberg, Bavaria, Germany", 48.17, 11.35)
    monkeypatch.setattr(openmeteo, "lookup", lookup)
    page = client.get("/suggest?sport=running&km=10&profile=flat&place=Starnberg").text
    assert page.count('class="card suggest-card"') == 3
    assert 'name="start_label" value="Starnberg, Bavaria, Germany"' in page


def take(client, **over):
    data = {"sport": "gravel_cycling", "km": "40", "profile": "flat", "lat": "48.17",
            "lon": "11.35", "heading": "30", "start_label": ""}
    return client.post("/suggest/take", data={**data, **over}, follow_redirects=False)


def test_take_over_makes_an_own_route(client, myauth, gh):
    login(client, myauth)
    r = take(client)
    with get_session() as s:
        route = s.exec(select(Route)).one()
    assert r.status_code == 303 and r.headers["location"] == f"/routes/{route.id}"
    assert route.name.startswith("Loop ") and route.name.endswith("hm")   # no place list
    assert route.source == "generated" and route.sports == ["gravel_cycling"] and route.loop
    assert route.description.startswith("Suggested by MyGPXContainer on ")
    assert "Gravel, Flat." in route.description
    assert (route.created_by_uid, route.created_by_username) == (7, "anna")
    assert gh.bodies[-1]["headings"] == [30]
    again = take(client)                                      # the same loop again
    assert again.headers["location"] == r.headers["location"]


def test_take_over_in_german_without_a_place_list(client, myauth, gh):
    login(client, myauth)
    myauth.body = {**USER, "language": "de"}
    take(client, sport="running", km="10", start_label="Starnberg, Bayern, Deutschland")
    with get_session() as s:
        route = s.exec(select(Route)).one()
    # the scheme is the same in every language: runs with one decimal, a point
    assert re.fullmatch(r"Starnberg \d+\.\dk \d+hm", route.name)
    assert route.description.startswith("Von MyGPXContainer vorgeschlagen am ")


def test_take_over_checks_what_it_gets(client, gh):
    assert take(client, sport="bmx").status_code == 422
    assert take(client, heading="45").status_code == 422
    assert take(client, km="1000").status_code == 422
    assert take(client, lat="99").status_code == 422
    gh.mode = "none"
    assert take(client).status_code == 404


# ---------- from A to B ----------

FINISH = (47.99, 11.13)


def test_via_points_beside_the_middle():
    mid = ((START[0] + FINISH[0]) / 2, (START[1] + FINISH[1]) / 2)
    d = suggest.gpx.haversine(START, FINISH)
    left, right = suggest.via(START, FINISH, -0.3), suggest.via(START, FINISH, 0.3)
    for v in (left, right):
        assert suggest.gpx.haversine(mid, v) == pytest.approx(0.3 * d, rel=0.02)
        # at a right angle: as far from A as from B
        assert suggest.gpx.haversine(START, v) == pytest.approx(suggest.gpx.haversine(FINISH, v), rel=0.02)
    assert suggest.gpx.haversine(left, right) == pytest.approx(0.6 * d, rel=0.02)


def test_three_ways_from_a_to_b(gh):
    routes = run(suggest.oneway("gravel_cycling", START, FINISH, "flat"))
    assert len(gh.bodies) == 5
    assert gh.bodies[0]["algorithm"] == "alternative_route" and len(gh.bodies[0]["points"]) == 2
    assert all(len(b["points"]) == 3 for b in gh.bodies[1:])            # over a point beside
    assert 1 < len(routes) <= 3 and len({r.key for r in routes}) == len(routes)
    assert {r.key for r in routes} <= set(suggest.ONEWAY_KEYS)
    assert routes[0].key == "a0"                  # the shortest, on gravel: best for gravel
    assert [r.score for r in routes] == sorted(r.score for r in routes)
    again = run(suggest.oneway_one("gravel_cycling", START, FINISH, "flat", routes[-1].key))
    assert again.key == routes[-1].key and again.km == pytest.approx(routes[-1].km)


def test_a_to_b_on_the_page(client, gh):
    url = f"/suggest?kind=oneway&sport=gravel_cycling&profile=flat&lat={START[0]}&lon={START[1]}"
    page = client.get(url + f"&to_lat={FINISH[0]}&to_lon={FINISH[1]}").text
    assert page.count('class="card suggest-card"') >= 2 and 'name="cand" value="a0"' in page
    lines = json.loads(page.split('id="suggest-lines">')[1].split("</script>")[0])
    assert lines["finish"] == list(FINISH)
    assert "Pick a destination." in client.get(url).text
    assert "are 909 km apart - more than the 300 km" in client.get(url + "&to_lat=40&to_lon=11").text
    assert "at least 1 km away" in client.get(url + f"&to_lat={START[0]}&to_lon={START[1]}").text


# ---------- names (places.json of the routing container) ----------

def place_list(*places):
    d = config.get_settings().routing_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / "places.json").write_text(json.dumps({"places": [list(p) for p in places]}))


def far_point(km, heading):
    """Where the fake loop of `km` with `heading` gets farthest from START."""
    lp = circle(START, km, heading)
    return max(lp, key=lambda p: suggest.gpx.haversine(START, p))


def test_loop_named_by_the_scheme(client, myauth, gh):
    login(client, myauth)
    far = far_point(40, 30)
    place_list((START[0] + 0.002, START[1], "town", "Starnberg"),
               (START[0] - 0.01, START[1], "village", "Too close to count"),
               (far[0] + 0.003, far[1], "village", "Percha"),
               (far[0] + 0.03, far[1], "suburb", "Not a town"))
    take(client)
    with get_session() as s:
        route = s.exec(select(Route)).one()
    assert re.fullmatch(r"Starnberg via Percha \d+k \d+hm", route.name)   # rides: whole km


def test_through_ones_own_town_the_suburb_counts(client, myauth, gh):
    login(client, myauth)
    far = far_point(10, 30)
    place_list((START[0], START[1] + 0.05, "city", "München"),
               (far[0] + 0.002, far[1], "suburb", "Schwabing"))
    take(client, sport="running", km="10")
    with get_session() as s:
        name = s.exec(select(Route)).one().name
    assert re.fullmatch(r"München via Schwabing \d+\.\dk \d+hm", name)   # runs: one decimal


def test_a_to_b_named_by_the_scheme(client, myauth, gh):
    login(client, myauth)
    place_list((START[0], START[1], "town", "Starnberg"), (FINISH[0], FINISH[1], "village", "Herrsching"))
    r = client.post("/suggest/take", data={
        "kind": "oneway", "sport": "road_biking", "profile": "flat", "lat": START[0],
        "lon": START[1], "to_lat": FINISH[0], "to_lon": FINISH[1], "cand": "v1"},
        follow_redirects=False)
    assert r.status_code == 303
    with get_session() as s:
        route = s.exec(select(Route)).one()
    assert re.fullmatch(r"Starnberg to Herrsching \d+k \d+hm", route.name) and not route.loop
    bad = {"kind": "oneway", "sport": "road_biking", "lat": START[0], "lon": START[1],
           "to_lat": FINISH[0], "to_lon": FINISH[1], "cand": "x9"}
    assert client.post("/suggest/take", data=bad).status_code == 422


def test_west_of_greenwich(client, gh):
    page = client.get("/suggest?sport=running&km=10&profile=flat&lat=51.5072&lon=-0.1276").text
    assert page.count('class="card suggest-card"') == 3


# ---------- addresses while typing (Photon) ----------

PHOTON = {"features": [
    {"geometry": {"coordinates": [11.3483, 48.1535]},
     "properties": {"name": "Alte Bahnhofstraße", "type": "street", "postcode": "82319",
                    "city": "Starnberg", "state": "Bayern", "country": "Deutschland",
                    "countrycode": "DE"}},
    {"geometry": {"coordinates": [11.3537, 48.1716]},
     "properties": {"street": "Bahnhofstraße", "housenumber": "5", "postcode": "82319",
                    "city": "Starnberg", "countrycode": "DE", "country": "Deutschland"}},
    {"geometry": {"coordinates": [11.574, 47.6805]},
     "properties": {"name": "Lenggries", "type": "city", "state": "Bayern",
                    "country": "Deutschland", "countrycode": "DE"}},
    {"geometry": {"coordinates": [-0.1276, 51.5072]},
     "properties": {"name": "London", "type": "city", "country": "Vereinigtes Königreich",
                    "countrycode": "GB"}},
]}


@pytest.fixture
def photon(monkeypatch):
    calls = []

    from app.geosearch import photon as block

    async def get_json(params):
        calls.append(params)
        return PHOTON
    monkeypatch.setattr(block, "_get_json", get_json)
    return calls


def test_addresses_while_typing(photon):
    hits = run(places.search("bahnhofstr puchh", "de", near=(48.17251, 11.35402)))
    assert [h["label"] for h in hits] == ["Alte Bahnhofstraße, 82319 Starnberg",
                                          "Bahnhofstraße 5, 82319 Starnberg",
                                          "Lenggries, Bayern", "London, Vereinigtes Königreich"]
    assert hits[3]["lon"] == -0.1276
    assert photon[0]["lat"] == 48.2 and photon[0]["lon"] == 11.4      # only ~10 km of the bias
    assert photon[0]["lang"] == "de" and photon[0]["limit"] == 6
    run(places.search("Bahnhofstr  Puchh", "de", near=(48.21, 11.37)))   # same ~10 km
    assert len(photon) == 1                                            # cached
    assert run(places.search("ab", "de")) == []


def test_places_endpoint_ranks_near_the_users_routes(client, myauth, photon):
    from app import routes
    from tests.conftest import make_gpx
    login(client, myauth)
    with get_session() as s:
        routes.create(s, make_gpx("Home", lat=48.17, lon=11.37), user=USER)
    hits = client.get("/suggest/places?q=Lenggries").json()
    assert hits[2] == {"label": "Lenggries, Bayern", "lat": 47.6805, "lon": 11.574}
    assert (photon[0]["lat"], photon[0]["lon"]) == (48.2, 11.4)        # from her own routes


def test_a_typed_place_is_looked_up_with_photon(client, gh, photon):
    page = client.get("/suggest?sport=running&km=10&profile=flat&place=Lenggries").text
    assert page.count('class="card suggest-card"') == 3
    assert 'name="start_label" value="Alte Bahnhofstraße, 82319 Starnberg"' in page   # first hit


def test_without_a_place_list_the_town_of_an_address():
    from app.pages import _town
    assert _town("Alte Bahnhofstraße, 82319 Starnberg") == "Starnberg"
    assert _town("Lenggries, Bayern") == "Lenggries"
    assert _town("London, Vereinigtes Königreich") == "London"
    assert _town("") == ""


# ---------- the longest routes (bike 300 km, on foot 100 km) ----------

def test_loops_that_come_out_too_long_get_a_corrected_round(gh):
    gh.length = {h: 1.22 for h in suggest.HEADINGS}       # like 300 km asked -> 366 km
    # cycling: the fake's gravel half would cost a road bike more than the length
    loops = run(suggest.suggest("cycling", START, 300, "flat"))
    asked = sorted({b["round_trip.distance"] for b in gh.bodies})
    assert len(gh.bodies) == 24 and asked[1] == 300000
    assert asked[0] == pytest.approx(300000 / 1.22, rel=0.005)   # corrected by how far off
    assert all(abs(lp.km - 300) / 300 < 0.05 for lp in loops)
    assert all(lp.asked_km == pytest.approx(300 / 1.22, rel=0.005) for lp in loops)


def test_close_loops_need_no_second_round(gh):
    run(suggest.suggest("road_biking", START, 100, "flat"))
    assert len(gh.bodies) == 12


def test_limits_per_sport(client, gh):
    page = client.get("/suggest?sport=running&km=150&profile=flat&lat=48&lon=11").text
    assert "Pick a distance from 2 to 100 km." in page and "Routes up to 100 km" in page
    page = client.get("/suggest?sport=road_biking&km=300&profile=flat&lat=48&lon=11").text
    assert page.count('class="card suggest-card"') == 3
    assert "from 2 to 300 km" in client.get("/suggest?sport=road_biking&km=301&lat=48&lon=11").text


def test_a_to_b_only_up_to_the_limit(gh, monkeypatch):
    monkeypatch.setitem(suggest.LIMIT_KM, "bike", 12)
    near = (START[0] - 0.1, START[1])                          # 11 km south
    routes = run(suggest.oneway("road_biking", START, near, "flat"))
    assert routes and all(r.km <= 12 for r in routes)          # the long detours are left out
    monkeypatch.setitem(suggest.LIMIT_KM, "bike", 5)
    with pytest.raises(suggest.Unavailable, match="longer than") as e:
        run(suggest.oneway("road_biking", START, near, "flat"))
    assert e.value.values == {"max": 5}


def test_take_over_asks_what_the_card_asked(client, myauth, gh):
    login(client, myauth)
    gh.length = {h: 1.22 for h in suggest.HEADINGS}
    page = client.get(f"/suggest?sport=road_biking&km=300&profile=flat&lat={START[0]}&lon={START[1]}").text
    asked = re.search(r'name="km" value="([0-9.]+)"', page.split('class="suggest-cards"')[1]).group(1)
    assert float(asked) == pytest.approx(300 / 1.22, rel=0.005)
    r = take(client, sport="road_biking", km=asked, heading="0")
    assert r.status_code == 303 and gh.bodies[-1]["round_trip.distance"] == round(float(asked) * 1000)
    assert take(client, sport="running", km="160").status_code == 422   # > 1.5 × 100


# ---------- elevation profiles on the cards ----------

def flat_loop(km, eles):
    """A straight line of `km` with these elevations, as a candidate."""
    n = len(eles)
    pts = [(48.0 + i * km / 111.32 / (n - 1), 11.0, e) for i, e in enumerate(eles)]
    return suggest.Loop(heading=0, points=pts, distance_m=km * 1000, ascent_m=0, profile="flat",
                        repeat=0, unpaved=0, big_roads=0)


def path_points(d):
    return [tuple(float(v) for v in part.split()) for part in d[1:].split(" L")]


def test_profiles_share_one_scale():
    from app.pages import _profiles
    a = flat_loop(20, [500, 600, 700, 600, 500])          # the highest point of all
    b = flat_loop(10, [450, 460, 470, 460, 450])          # half as long, the lowest point
    pa, pb = _profiles([a, b])
    xa, ya = zip(*path_points(pa["line"]))
    xb, yb = zip(*path_points(pb["line"]))
    assert max(xa) == 100 and max(xb) == pytest.approx(50, abs=0.5)   # same km scale
    assert min(ya) == 0 and max(yb) == 40                              # same metres
    assert (pa["lo"], pa["hi"], pb["lo"], pb["hi"]) == (500, 700, 450, 470)
    assert pa["area"].startswith(pa["line"]) and pa["area"].endswith("Z")


def test_a_flat_route_does_not_look_hilly():
    from app.pages import _profiles
    flat, = _profiles([flat_loop(10, [500, 505, 510, 505, 500])])      # 10 m up and down
    ys = [y for _, y in path_points(flat["line"])]
    assert max(ys) - min(ys) < 40 * 10 / 60 + 0.1                      # at most 10 of 60 m


def test_profiles_on_the_cards(client, gh):
    page = client.get(f"/suggest?sport=cycling&km=40&profile=flat&lat={START[0]}&lon={START[1]}").text
    assert page.count('class="suggest-profile loop-c') == 3 and "Elevation 500–" in page
