"""Map regions of the loop suggestions: the admin page, regions.json for the
routing container and its status.json - Geofabrik's index is faked."""

import json

import pytest
from sqlmodel import select

from app import config, routing, suggest
from app.db import get_session
from app.models import RoutingRegion
from tests.conftest import USER

GF = "https://download.geofabrik.de/"
FIRST = [{"id": "germany", "name": "Germany", "pbf": GF + "europe/germany-latest.osm.pbf"},
         {"id": "greater-london", "name": "Greater London",
          "pbf": GF + "europe/united-kingdom/england/greater-london-latest.osm.pbf"}]
INDEX = [
    {"id": "europe", "name": "Europe", "urls": {"pbf": GF + "europe-latest.osm.pbf"}},
    {"id": "germany", "name": "Germany", "parent": "europe",
     "urls": {"pbf": GF + "europe/germany-latest.osm.pbf"}},
    {"id": "bayern", "name": "Bayern", "parent": "germany",
     "urls": {"pbf": GF + "europe/germany/bayern-latest.osm.pbf"}},
    {"id": "austria", "name": "Austria", "parent": "europe",
     "urls": {"pbf": GF + "europe/austria-latest.osm.pbf"}},
    {"id": "africa", "name": "Africa", "urls": {"pbf": GF + "africa-latest.osm.pbf"}},
    {"id": "canary-islands", "name": "Canary Islands", "parent": "africa",
     "urls": {"pbf": GF + "africa/canary-islands-latest.osm.pbf"}},
    {"id": "no-pbf", "name": "Nothing to load", "urls": {}},
]


@pytest.fixture(autouse=True)
def geofabrik(monkeypatch):
    calls = []

    async def get_index():
        calls.append(1)
        return INDEX
    monkeypatch.setattr(routing, "_get_index", get_index)
    monkeypatch.setattr(routing, "_index", None)
    monkeypatch.setattr(routing, "FIRST", FIRST)       # as the first instance started
    return calls


def wish():
    return json.loads((config.get_settings().routing_dir / "regions.json").read_text())


def status(**st):
    d = config.get_settings().routing_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / "status.json").write_text(json.dumps(st))


def ids():
    return [r["id"] for r in wish()["regions"]]


def test_germany_and_london_on_first_start_and_never_again(client):
    assert ids() == ["germany", "greater-london"] and wish()["rebuild"] == ""
    assert wish()["regions"][0]["pbf"] == GF + "europe/germany-latest.osm.pbf"
    for gid in ("germany", "greater-london"):
        client.post("/admin/routing/remove", data={"region": gid})
    assert ids() == []
    with get_session() as s:
        routing.setup(s)                 # the next start: stays empty
    assert ids() == []


def test_add_search_and_coverage(client, geofabrik):
    page = client.get("/admin/routing?q=can").text
    assert "Canary Islands" in page and "Africa" in page          # with where it lies
    assert ">Germany <" not in page.split("Add a region")[1]       # on the list already
    client.post("/admin/routing/add", data={"region": "canary-islands"})
    assert ids() == ["canary-islands", "germany", "greater-london"]
    r = client.post("/admin/routing/add", data={"region": "bayern"}, follow_redirects=False)
    assert "problem=" in r.headers["location"]
    assert ids() == ["canary-islands", "germany", "greater-london"]
    assert "“Bayern” is already covered by “Germany”." in client.get(r.headers["location"]).text
    client.post("/admin/routing/add", data={"region": "europe"})  # covers Germany
    assert ids() == ["canary-islands", "europe", "greater-london"]   # London: not in the fake index
    assert "Unknown region" in client.post("/admin/routing/add", data={"region": "no-pbf"}).text
    assert len(geofabrik) == 1                                     # the index once a day


def test_rebuild_asks_for_fresh_data_and_keeps_the_token(client):
    client.post("/admin/routing/rebuild")
    token = wish()["rebuild"]
    assert token
    client.post("/admin/routing/add", data={"region": "austria"})
    assert wish()["rebuild"] == token and ids() == ["austria", "germany", "greater-london"]


def test_status_on_the_page(client):
    assert "Routing service not reached yet" in client.get("/admin/routing").text
    status(state="serving", serving=True, names=["Germany"], built_at="2026-10-30T09:26:16Z",
           build_seconds=1500, graph_mb=2900)
    page = client.get("/admin/routing").text
    assert "Ready" in page and "Built: Germany" in page and "in 25 min, 2900 MB" in page
    status(state="building", serving=True, names=["Germany"],
           building={"step": "downloading Austria", "regions": ["austria", "germany"],
                     "since": "2026-10-30T10:00:00Z"}, error="import failed (exit 1)")
    page = client.get("/admin/routing").text
    assert "Building" in page and "Now: downloading Austria (austria, germany)" in page
    assert "Last build failed: import failed (exit 1)" in page and "data-building" in page


def test_only_app_admins(client, myauth):
    myauth.body = dict(USER)                       # app_admin False
    client.cookies.set("sso_session", "u")
    assert client.get("/admin/routing").status_code == 403
    assert client.post("/admin/routing/add", data={"region": "austria"}).status_code == 403
    assert client.post("/admin/routing/remove", data={"region": "germany"}).status_code == 403
    assert client.post("/admin/routing/rebuild").status_code == 403
    assert 'href="/admin/routing"' not in client.get("/").text
    assert ids() == ["germany", "greater-london"]
    myauth.body = {**USER, "app_admin": True}
    client.cookies.set("sso_session", "a")
    assert client.get("/admin/routing").status_code == 200
    assert 'href="/admin/routing"' in client.get("/").text
    client.post("/admin/routing/add", data={"region": "austria"})
    with get_session() as s:
        row = s.exec(select(RoutingRegion).where(RoutingRegion.geofabrik_id == "austria")).one()
    assert (row.added_by_uid, row.added_by_username) == (7, "anna")


def test_suggestions_say_when_the_map_is_being_built(client, monkeypatch):
    async def down(body):
        raise suggest.Unavailable("Suggestions are not available right now. "
                                  "Please try again in a minute.")
    monkeypatch.setattr(suggest, "_route", down)
    url = "/suggest?sport=cycling&km=30&lat=48&lon=11"
    assert "not available right now" in client.get(url).text
    status(state="building", serving=False, building={"step": "importing", "regions": ["germany"],
                                                      "since": "2026-10-30T10:00:00Z"})
    assert "The map is being built" in client.get(url).text
