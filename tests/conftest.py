"""Test fixtures: an isolated data dir, a fresh DB and settings for every test.
No test talks to a real MyAuth or geocoder: `access.myauth._fetch_session(cookie)` is
replaced where a test needs a login (fixture `myauth`), `_fetch_garmin(uid)` where it
needs a Garmin token, `auth.myauth._fetch_members(uid)` where it needs the users to
share with."""

import email
import json
import os

import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MGC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("MGC_AUTH_URL", raising=False)
    monkeypatch.setenv("MGC_AUTH", "none")         # no sign-in unless a test turns it on
    from app import config, db, pages
    from app.access import myauth
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "_engine", None)
    myauth.clear_cache()
    pages._display.cache_clear()
    pages._outline.cache_clear()
    pages._sketch.cache_clear()
    monkeypatch.setattr(pages, "_device_tries", {})
    from app import garmin_sync
    from app.auth import myauth as auth_myauth
    monkeypatch.setattr(garmin_sync, "_runs", {})
    monkeypatch.setattr(auth_myauth, "_members", {})
    from app.auth import garmin_link
    monkeypatch.setattr(garmin_link, "_sealer", None)
    garmin_link._signins.clear()
    from app import geocode

    async def no_geocoding(params):
        raise httpx.ConnectError("no network in tests")
    monkeypatch.setattr(geocode, "_get_json", no_geocoding)
    monkeypatch.setattr(geocode, "_cache", {})
    from collections import OrderedDict

    from app import places

    async def no_photon(path, params):
        raise httpx.ConnectError("no network in tests")
    monkeypatch.setattr(places, "_get_json", no_photon)
    monkeypatch.setattr(places, "_cache", OrderedDict())
    monkeypatch.setattr(places, "_grid", None)
    yield


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app, base_url="https://phoenix.example:1016") as c:
        yield c


USER = {"uid": 7, "username": "anna", "display_name": "Anna Muster", "language": "en",
        "app_admin": False, "impersonated_by": None}


@pytest.fixture
def myauth(monkeypatch):
    """Login on: MyAuth answers with `myauth.status`/`myauth.body`."""
    monkeypatch.setenv("MGC_AUTH_URL", "http://myauth:8000")
    monkeypatch.setenv("MGC_AUTH", "myauth")
    from app import config
    monkeypatch.setattr(config, "_settings", None)   # the client may have read them already

    class Fake:
        status = 200
        body = dict(USER)
        calls = 0

    async def fetch(cookie):
        Fake.calls += 1
        return Fake.status, Fake.body
    from app.access import myauth
    monkeypatch.setattr(myauth, "_fetch_session", fetch)
    return Fake


def make_gpx(name="Test route", lat=48.0, lon=11.0, n=20, step=0.001, ele=True) -> bytes:
    """A small synthetic GPX track heading north (never anyone's real route)."""
    pts = "".join(
        f'<trkpt lat="{lat + i * step:.6f}" lon="{lon:.6f}">'
        + (f"<ele>{500 + i}</ele>" if ele else "") + "</trkpt>" for i in range(n))
    return (f'<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">'
            f"<trk><name>{name}</name><trkseg>{pts}</trkseg></trk></gpx>").encode()


def gpx_upload(request: httpx.Request) -> bytes:
    """The file of a multipart upload (Garmin's course import)."""
    msg = email.message_from_bytes(b"Content-Type: " + request.headers["content-type"].encode()
                                   + b"\r\n\r\n" + request.content)
    return msg.get_payload()[0].get_payload(decode=True)


def fake_client(handler):
    """garmin_courses._client for the tests: the block's client with the
    token, its HTTP answered by `handler(token, request)` - nothing leaves.
    Call it before patching: it builds on the real `_client`."""
    from app import garmin_courses
    build = garmin_courses._client

    def make(token):
        client = build(token)

        def answer(request: httpx.Request) -> httpx.Response:
            request.read()
            return handler(request.headers["authorization"].removeprefix("Bearer "), request)
        client._http = httpx.AsyncClient(transport=httpx.MockTransport(answer))
        return client
    return make


class FakeGarmin:
    """One Garmin account per token: its courses by id."""

    def __init__(self):
        self.accounts: dict[str, dict[int, dict]] = {}
        self.next_id = 1000
        self.calls: list[tuple[str, str, str]] = []
        self.fail_create = False
        self.busy_deletes = 0           # 429 "not yet ready" this many times
        self.devices: list[dict] | dict[str, list[dict]] = []   # one list, or per token
        self.messages: list[dict] = []  # device messages (courses sent to devices)

    def request(self, token, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path
        self.calls.append((token, method, path))
        courses = self.accounts.setdefault(token, {})
        if path == "/device-service/deviceregistration/devices":
            self.device_lookups = getattr(self, "device_lookups", 0) + 1
            devs = self.devices.get(token, []) if isinstance(self.devices, dict) else self.devices
            return httpx.Response(200, json=devs)
        if path == "/device-service/devicemessage/messages" and method == "POST":
            self.messages += json.loads(request.content)
            return httpx.Response(200, json=[{"messageId": len(self.messages)}])
        if path == "/userprofile-service/socialProfile":
            return httpx.Response(200, json={"displayName": "dn-" + token})
        if path.startswith("/course-service/course/owner/"):
            return httpx.Response(200, json=[        # like Garmin: no description here
                {"courseId": i, "courseName": c["courseName"], "courseDescription": None}
                for i, c in courses.items()])
        if path == "/course-service/course/import":
            from app import gpx
            data = gpx_upload(request)
            pts = gpx.parse(data).points
            dist = gpx.distances(pts)
            return httpx.Response(200, json={"courseName": "x", "geoPoints": [
                {"latitude": p[0], "longitude": p[1], "elevation": None, "distance": d}
                for p, d in zip(pts, dist)]})
        if method == "POST" and path == "/course-service/course":
            if self.fail_create:
                return httpx.Response(500, text="boom")
            self.next_id += 1
            courses[self.next_id] = json.loads(request.content)
            return httpx.Response(200, json={"courseId": self.next_id})
        if method == "GET" and path.startswith("/course-service/course/"):
            c = courses.get(int(path.rsplit("/", 1)[1]))
            return httpx.Response(200, json=c) if c else httpx.Response(404)
        if method == "DELETE":
            if self.busy_deletes:
                self.busy_deletes -= 1
                return httpx.Response(429, json={"message": "not yet ready"})
            cid = int(path.rsplit("/", 1)[1])
            return httpx.Response(204 if courses.pop(cid, None) else 404)
        return httpx.Response(404)


@pytest.fixture
def garmin(monkeypatch):
    """A fake Garmin (one account per token) and a MyAuth that hands out
    tokens "tok<uid>" - uid 99 is not connected."""
    from app import config, garmin_courses
    from app.access import myauth
    fake = FakeGarmin()
    monkeypatch.setattr(garmin_courses, "_client", fake_client(fake.request))

    async def no_wait(seconds):
        fake.waited += seconds
    fake.waited = 0
    monkeypatch.setattr(garmin_courses, "_sleep", no_wait)
    monkeypatch.setenv("MGC_AUTH_URL", "http://myauth:8000")
    if os.environ.get("MGC_AUTH") == "none":       # a test of own accounts keeps its mode
        monkeypatch.setenv("MGC_AUTH", "myauth")
    monkeypatch.setenv("MYAUTH_APP_KEY", "secret")
    monkeypatch.setattr(config, "_settings", None)

    async def token(uid):
        return (200, {"access_token": f"tok{uid}"}) if uid != 99 else (404, {})
    monkeypatch.setattr(myauth, "_fetch_garmin", token)
    return fake
