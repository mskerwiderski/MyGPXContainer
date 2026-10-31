"""Share links. No test goes on the network: each source's mock point
(`_get_json`, `_get`, `_public`; Garmin `garmin_courses._client`) and MyAuth's
`_fetch_garmin` are replaced."""

import asyncio

import httpx
import pytest
from sqlmodel import select

from app import garmin_courses, sources
from app.access import myauth
from app.db import get_session
from app.models import Route
from app.sources import komoot, link
from tests.conftest import USER, fake_client, make_gpx

KOMOOT_URL = "https://www.komoot.com/de-DE/tour/123456?share_token=abc&ref=its"
TOUR = {"name": "Isar Gravel", "sport": "mtb_easy",
        "_embedded": {"coordinates": {"items": [
            {"lat": 48.10, "lng": 11.50, "alt": 520.0, "t": 0},
            {"lat": 48.11, "lng": 11.51, "alt": 530.5, "t": 1000},
            {"lat": 48.12, "lng": 11.50, "alt": 525.0, "t": 2000}]}}}


def routes_in_db():
    with get_session() as s:
        return s.exec(select(Route)).all()


@pytest.fixture
def komoot_api(monkeypatch):
    calls = []

    async def get_json(url, params):
        calls.append((url, params))
        return komoot_api.status, komoot_api.body
    komoot_api.status, komoot_api.body, komoot_api.calls = 200, TOUR, calls
    monkeypatch.setattr(komoot, "_get_json", get_json)
    return komoot_api


def add(client, url, **data):
    return client.post("/routes/link", data={"url": url, **data}, follow_redirects=False)


# ---------- Komoot ----------

def test_komoot_tour_becomes_a_route(client, komoot_api):
    r = add(client, KOMOOT_URL)
    assert r.status_code == 303
    route = routes_in_db()[0]
    assert r.headers["location"] == f"/routes/{route.id}"
    assert (route.name, route.source, route.external_id) == ("Isar Gravel", "komoot", "123456")
    assert route.sports == ["gravel_cycling"] and route.source_url == KOMOOT_URL
    assert route.point_count == 3 and route.ascent_m == 10
    url, params = komoot_api.calls[0]
    assert url.endswith("/tours/123456") and params["share_token"] == "abc"
    assert "Komoot" in client.get(f"/routes/{route.id}").text


def test_own_sports_win_over_komoots(client, komoot_api):
    add(client, KOMOOT_URL, sports=["mountain_biking"])
    assert routes_in_db()[0].sports == ["mountain_biking"]


def test_komoot_without_share_token(client, komoot_api):
    komoot_api.status, komoot_api.body = 403, {}
    r = add(client, "https://www.komoot.de/tour/123456")
    assert r.status_code == 422 and "share link" in r.text
    assert 'value="https://www.komoot.de/tour/123456"' in r.text and routes_in_db() == []


def test_same_tour_twice_is_a_duplicate_even_if_changed(client, komoot_api):
    add(client, KOMOOT_URL)
    komoot_api.body = {**TOUR, "name": "Isar Gravel v2"}
    r = add(client, KOMOOT_URL)
    assert r.status_code == 422 and "already here" in r.text and len(routes_in_db()) == 1


def test_komoot_link_without_tour(client, komoot_api):
    r = add(client, "https://www.komoot.com/de-de/user/42")
    assert "does not point to a tour" in r.text and komoot_api.calls == []


# ---------- Garmin Connect ----------

COURSE = {"courseName": "Lake loop", "description": "Flat", "activityTypePk": 143}


@pytest.fixture
def garmin_api(monkeypatch):
    seen = {"tokens": [], "paths": []}

    async def fetch_garmin(uid):
        seen["tokens"].append((uid, myauth.app_secret()))
        return garmin_api.token_status, {"access_token": "tok-" + str(uid)}

    def get(token, request):
        path = request.url.path
        seen["paths"].append((token, path))
        if "/gpx/" in path:
            return httpx.Response(200, content=make_gpx("from garmin"))
        return httpx.Response(garmin_api.info_status, json=COURSE)
    garmin_api.token_status, garmin_api.info_status, garmin_api.seen = 200, 200, seen
    monkeypatch.setattr(myauth, "_fetch_garmin", fetch_garmin)
    monkeypatch.setattr(garmin_courses, "_client", fake_client(get))
    return garmin_api


def login(client, myauth, monkeypatch):
    monkeypatch.setenv("MYAUTH_APP_KEY", "secret")
    from app import config
    monkeypatch.setattr(config, "_settings", None)
    myauth.body = dict(USER)
    client.cookies.set("sso_session", "abc")


def test_garmin_course_with_the_users_own_token(client, myauth, garmin_api, monkeypatch):
    login(client, myauth, monkeypatch)
    r = add(client, "https://connect.garmin.com/modern/course/526970098")
    assert r.status_code == 303
    route = routes_in_db()[0]
    assert (route.name, route.description, route.sports) == ("Lake loop", "Flat",
                                                             ["gravel_cycling"])
    assert (route.source, route.external_id) == ("garmin", "526970098")
    assert garmin_api.seen["tokens"] == [(7, "secret")]
    assert {p for _, p in garmin_api.seen["paths"]} == {
        "/course-service/course/526970098", "/course-service/course/gpx/526970098"}


def test_garmin_not_connected(client, myauth, garmin_api, monkeypatch):
    login(client, myauth, monkeypatch)
    garmin_api.token_status = 404
    r = add(client, "https://connect.garmin.com/app/course/1")
    assert r.status_code == 422 and "not connected" in r.text


def test_garmin_foreign_private_course(client, myauth, garmin_api, monkeypatch):
    login(client, myauth, monkeypatch)
    garmin_api.info_status = 403
    r = add(client, "https://connect.garmin.com/modern/course/1")
    assert "Only your own and public courses" in r.text


def test_garmin_errors_name_garmin(client, myauth, garmin_api, monkeypatch):
    login(client, myauth, monkeypatch)
    garmin_api.info_status = 500
    r = add(client, "https://connect.garmin.com/modern/course/1")
    assert "Garmin Connect answered with an error (500)" in r.text

    def unreachable(token, request):
        raise httpx.ConnectError("down", request=request)
    monkeypatch.setattr(garmin_courses, "_client", fake_client(unreachable))
    r = add(client, "https://connect.garmin.com/modern/course/1")
    assert "Garmin Connect is not reachable right now" in r.text


def test_garmin_without_app_key(client, garmin_api):
    r = add(client, "https://connect.garmin.com/modern/course/1")
    assert "not set up" in r.text and garmin_api.seen["tokens"] == []


# ---------- any GPX link ----------

@pytest.fixture
def web(monkeypatch):
    async def public(host, port):
        return host not in ("intranet.local", "192.168.1.20")

    async def get(url):
        web.urls.append(url)
        return web.responses.get(url, (404, {}, b""))
    web.urls, web.responses = [], {}
    monkeypatch.setattr(link, "_public", public)
    monkeypatch.setattr(link, "_get", get)
    return web


def test_gpx_link_follows_redirects(client, web):
    web.responses = {
        "https://example.org/r/1": (302, {"location": "/files/Hill%20Run.gpx"}, b""),
        "https://example.org/files/Hill%20Run.gpx": (200, {}, make_gpx("").replace(
            b"<name></name>", b"")),
    }
    assert add(client, "https://example.org/r/1").status_code == 303
    route = routes_in_db()[0]
    assert (route.name, route.source, route.source_url) == ("Hill Run", "url",
                                                            "https://example.org/r/1")


def test_gpx_link_into_the_home_network_is_refused(client, web):
    r = add(client, "http://192.168.1.20:1000/x.gpx")
    assert "not lead to a public website" in r.text and web.urls == []


def test_redirect_into_the_home_network_is_refused(client, web):
    web.responses = {"https://example.org/x": (302, {"location": "http://intranet.local/a"}, b"")}
    r = add(client, "https://example.org/x")
    assert "not lead to a public website" in r.text and web.urls == ["https://example.org/x"]


def test_link_that_is_no_gpx(client, web):
    web.responses = {"https://example.org/page": (200, {}, b"<html></html>")}
    assert "not a valid GPX file" in add(client, "https://example.org/page").text


def test_not_a_web_link(client, web):
    assert "starting with https://" in add(client, "file:///etc/passwd").text


def test_public_check_rejects_private_addresses():
    for host in ("localhost", "127.0.0.1", "10.1.2.3", "192.168.1.20", "::1", "169.254.1.1"):
        assert not asyncio.run(link._public(host, 80)), host


def test_kind():
    assert sources.kind("https://www.komoot.de/tour/1") == "komoot"
    assert sources.kind("https://komoot.com/tour/1") == "komoot"
    assert sources.kind("https://connect.garmin.com/modern/course/1") == "garmin"
    assert sources.kind("https://notkomoot.com/tour/1") == "url"


def test_only_ports_80_and_443(client, monkeypatch):
    from app.sources import link

    async def public(host, port):
        return True
    monkeypatch.setattr(link, "_public", public)
    r = client.post("/routes/link", data={"url": "https://example.org:8080/x.gpx"})
    assert "does not lead to a public website" in r.text


def test_the_connected_address_is_checked_again():
    """DNS rebinding: the name may resolve differently when httpx connects."""
    from app.sources import link

    class Stream:
        def __init__(self, addr):
            self.addr = addr

        def get_extra_info(self, key):
            return (self.addr, 443) if key == "server_addr" else None

    class Resp:
        def __init__(self, addr):
            self.extensions = {"network_stream": Stream(addr)} if addr else {}
    assert link._connected_to_public(Resp("93.184.215.14"))
    for addr in ("127.0.0.1", "192.168.1.20", "169.254.169.254", "::1", "172.18.0.5", None):
        assert not link._connected_to_public(Resp(addr))
