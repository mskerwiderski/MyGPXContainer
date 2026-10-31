from datetime import datetime, timedelta, timezone

from app import geocode
from app.models import Route
from app.search import Filters, apply
from tests.conftest import USER, make_gpx

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def route(name, km, up, sports, *, desc="", loop=False, by="", lat=48.17, lon=11.35, age=0):
    """`by`: who shared it (a copy), "" for the user's own route."""
    return Route(uid=name, name=name, description=desc, sports=sports, gpx_sha=name,
                 distance_m=km * 1000, ascent_m=up, start_lat=lat, start_lon=lon,
                 min_lat=lat, min_lon=lon, max_lat=lat, max_lon=lon, loop=loop, point_count=2,
                 created_by_username="anna", shared_by_username=by,
                 shared_from="orig-" + name if by else "", created_at=T0 - timedelta(days=age))


R = [route("Gravel 90", 40.7, 224, ["gravel_cycling"], loop=True, desc="Über Feldwege"),
     route("Isar Trail", 21, 410, ["trail_running"], by="ben", lat=48.0, lon=11.5, age=1),
     route("Lake walk", 6, None, ["hiking", "walking"], lat=47.9, lon=11.3, age=2)]


def names(f, **kw):
    return [r.name for r, _ in apply(R, f, **kw)]


def test_defaults_newest_first():
    assert names(Filters.parse({})) == ["Gravel 90", "Isar Trail", "Lake walk"]


def test_text_folds_case_and_umlauts_every_word_must_match():
    assert names(Filters.parse({"q": "ÜBER feld"})) == ["Gravel 90"]
    assert names(Filters.parse({"q": "trail gravel"})) == []


def test_sport_and_group():
    assert names(Filters.parse({"sport": "hiking"})) == ["Lake walk"]
    assert names(Filters.parse({"sport": "g:run"})) == ["Isar Trail"]
    assert names(Filters.parse({"sport": "g:nonsense"})) == names(Filters.parse({}))


def test_distance_ascent_shape_from():
    assert names(Filters.parse({"dmin": "10", "dmax": "30"})) == ["Isar Trail"]
    assert names(Filters.parse({"amax": "300"})) == ["Gravel 90"]   # no heights: left out
    assert names(Filters.parse({"shape": "loop"})) == ["Gravel 90"]
    assert names(Filters.parse({"shape": "oneway"})) == ["Isar Trail", "Lake walk"]
    assert names(Filters.parse({"by": "ben"})) == ["Isar Trail"]           # shared by Ben
    assert names(Filters.parse({"by": "me"})) == ["Gravel 90", "Lake walk"]  # not shared
    assert names(Filters.parse({"dmin": "1,5", "dmax": "x"})) == names(Filters.parse({}))


def test_only_in_my_garmin():
    assert names(Filters.parse({"garmin": "1"}), in_garmin={"Lake walk"}) == ["Lake walk"]


def test_near_sorts_by_distance_and_cuts_at_the_radius():
    f = Filters.parse({"lat": "47.9", "lon": "11.3", "radius": "25"})
    assert f.sort == "near"
    found = apply(R, f, center=(47.9, 11.3))
    assert [r.name for r, _ in found] == ["Lake walk", "Isar Trail"]
    assert found[0][1] == 0
    assert names(Filters.parse({"radius": "100", "sort": "distance"}),
                 center=(47.9, 11.3)) == ["Lake walk", "Isar Trail", "Gravel 90"]


def test_active_count():
    assert Filters.parse({}).active() == 0
    assert Filters.parse({"q": "x", "sport": "hiking", "view": "map", "sort": "name"}).active() == 2
    assert Filters.parse({"place": "Roth"}).active() == 1


# ---------- page ----------

def upload(client, name, lon=11.0):
    client.post("/routes", files=[("files", (f"{name}.gpx", make_gpx(name, lon=lon),
                                             "application/gpx+xml"))],
                data={"sports": ["hiking"]})


def test_filtered_page_and_counts(client):
    upload(client, "Alpha")
    upload(client, "Beta", lon=12.0)
    page = client.get("/?q=alp").text
    assert "1 of 2 routes" in page and ">Alpha</a>" in page and ">Beta</a>" not in page
    assert 'id="filter-count"' in page


def test_map_view_carries_the_start_points(client):
    upload(client, "Alpha")
    page = client.get("/?view=map").text
    assert 'id="overview-map"' in page and '"name":"Alpha","lat":48.0,"lon":11.0' in page
    assert '"line":[[48.0,11.0],[48.001,11.0]' in page
    assert '"line"' not in client.get("/").text            # the list view needs no lines


def test_place_is_geocoded(client, monkeypatch):
    async def fake(params):
        assert params["name"] == "Starnberg"
        return {"results": [{"name": "Starnberg", "admin1": "Bavaria", "country": "Germany",
                             "latitude": 48.0, "longitude": 11.0}]}
    monkeypatch.setattr(geocode, "_get_json", fake)
    upload(client, "Alpha")
    upload(client, "Far away", lon=13.0)
    page = client.get("/?place=Starnberg&radius=10").text
    assert "within 10 km of Starnberg, Bavaria, Germany" in page
    assert ">Alpha</a>" in page and ">Far away</a>" not in page


def test_unknown_place(client):
    upload(client, "Alpha")
    assert "Place “Nowhere” not found" in client.get("/?place=Nowhere").text


def test_from_filter_only_once_something_was_shared(client, myauth):
    myauth.body = dict(USER)
    client.cookies.set("sso_session", "abc")
    upload(client, "Alpha")
    page = client.get("/").text
    assert 'name="by"' not in page and 'class="r-by"' not in page


def test_profile_bounds():
    from app.sports import profile
    assert profile(10_000, 69) == "flat"
    assert profile(10_000, 70) == "hilly"
    assert profile(27_600, 1675) == "mountainous"
    assert profile(10_000, None) is None


def test_profile_bounds_on_foot():
    from app.sports import profile
    assert profile(15_000, 265, ["hiking"]) == "flat"              # 17.7 m/km
    assert profile(15_000, 265, ["gravel_cycling"]) == "mountainous"
    assert profile(10_000, 200, ["running", "hiking"]) == "hilly"
    assert profile(10_000, 500, ["trail_running"]) == "mountainous"
    assert profile(10_000, 200, ["hiking", "mountain_biking"]) == "mountainous"   # by bike
    assert profile(10_000, 200, []) == "mountainous"               # no sport: by bike


def test_profile_filter():
    # Isar Trail: trail running, 19.5 m/km - flat on foot (by bike it would be mountainous)
    assert names(Filters.parse({"profile": "mountainous"})) == []
    assert names(Filters.parse({"profile": "hilly"})) == []
    assert names(Filters.parse({"profile": "flat"})) == ["Gravel 90", "Isar Trail"]   # Lake walk: no heights
    assert Filters.parse({"profile": "steep"}).profile == ""


def test_tags_and_sketch_in_the_list(client):
    upload(client, "Alpha")
    page = client.get("/").text
    assert '<svg class="sketch" viewBox="0 0 100 100"' in page
    assert ">Point to point</span>" in page and 'class="badge tag tag-' in page
