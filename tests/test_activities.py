"""Garmin activities as routes (activities.py) against a fake Garmin: an
activity list, details and GPX exports with times and heart rate."""

import json

import httpx
import pytest
from sqlmodel import select

from app import activities, garmin_courses
from app.db import get_session
from app.models import Route
from tests.conftest import USER, FakeGarmin, fake_client


def track_gpx(name, lat=48.17, lon=11.35, n=60, still=0):
    """Heading north, every point with time and heart rate; `still` points
    of standing still (GPS jitter around one spot) in the middle."""
    pts = [(lat + i * 0.0005, lon) for i in range(n // 2)]
    mid = pts[-1]
    pts += [(mid[0] + (k % 3) * 0.00001, mid[1] + (k % 2) * 0.00001) for k in range(still)]
    pts += [(mid[0] + (i + 1) * 0.0005, lon) for i in range(n - n // 2)]
    seg = "".join(f'<trkpt lat="{a:.6f}" lon="{b:.6f}"><ele>{500 + i * 0.5:.1f}</ele>'
                  f"<time>2026-11-01T08:{i // 60 % 60:02d}:{i % 60:02d}Z</time><extensions>"
                  f"<ns3:TrackPointExtension><ns3:hr>{120 + i % 30}</ns3:hr>"
                  f"</ns3:TrackPointExtension></extensions></trkpt>"
                  for i, (a, b) in enumerate(pts))
    return (f'<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1" '
            f'xmlns:ns3="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">'
            f"<trk><name>{name}</name><trkseg>{seg}</trkseg></trk></gpx>").encode()


ACTS = {
    101: {"activityName": "Puchheim Laufen", "type": "running", "km": 7.8, "gps": True},
    102: {"activityName": "Rolle", "type": "indoor_cycling", "km": 30, "gps": False},
    103: {"activityName": "Triathlon", "type": "multi_sport", "km": 40, "gps": True,
          "children": [104, 105]},
    104: {"activityName": "Triathlon Rad", "type": "road_biking", "km": 30, "gps": True,
          "parent": 103},
    105: {"activityName": "Triathlon Lauf", "type": "running", "km": 10, "gps": True,
          "parent": 103},
    900: {"activityName": "Someone else's", "type": "cycling", "km": 20, "gps": True,
          "foreign": True},
}


class FakeActivities(FakeGarmin):
    def __init__(self):
        super().__init__()
        self.list_params = []

    def request(self, token, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/activitylist-service/activities/search/activities":
            self.list_params.append(dict(request.url.params))
            kind = request.url.params.get("activityType")
            rows = [{"activityId": i, "activityName": a["activityName"],
                     "activityType": {"typeKey": a["type"]}, "distance": a["km"] * 1000,
                     "elevationGain": 30, "startTimeLocal": "2026-11-01 08:00:00",
                     "hasPolyline": a["gps"], **({"parentId": a["parent"]} if "parent" in a else {}),
                     **({"childIds": a["children"]} if "children" in a else {})}
                    for i, a in ACTS.items() if not a.get("foreign")
                    and (not kind or a["type"] == kind)]
            start = int(request.url.params.get("start", 0))
            limit = int(request.url.params.get("limit", 20))
            return httpx.Response(200, json=rows[start:start + limit])
        if path.startswith("/activity-service/activity/"):
            aid = int(path.rsplit("/", 1)[1])
            a = ACTS.get(aid)
            if a is None:
                return httpx.Response(404)
            if a.get("foreign"):
                return httpx.Response(403)
            return httpx.Response(200, json={
                "activityId": aid, "activityName": a["activityName"],
                "activityTypeDTO": {"typeKey": a["type"]},
                "summaryDTO": {"startTimeLocal": "2026-11-01T08:00:00.0",
                               "distance": a["km"] * 1000, "elevationGain": 30},
                "metadataDTO": {"childIds": a.get("children"), "hasPolyline": a["gps"]}})
        if path.startswith("/download-service/export/gpx/activity/"):
            aid = int(path.rsplit("/", 1)[1])
            if ACTS.get(aid, {}).get("foreign"):
                return httpx.Response(403)
            return httpx.Response(200, content=track_gpx(ACTS[aid]["activityName"], still=20))
        return super().request(token, request)


@pytest.fixture
def acts(garmin, monkeypatch):
    fake = FakeActivities()
    monkeypatch.setattr(garmin_courses, "_client", fake_client(fake.request))
    return fake


def login(client, myauth, **user):
    myauth.body = {**USER, **user}
    client.cookies.set("sso_session", "x" + json.dumps(user))


def only_route():
    with get_session() as s:
        return s.exec(select(Route)).one()


def test_clean_takes_the_knot_out():
    from app import gpx
    pts = gpx.parse(track_gpx("x", still=40)).points
    kept = activities.clean(pts)
    assert len(pts) == 100 and len(kept) <= 61 and kept[0] == pts[0] and kept[-1] == pts[-1]
    assert all(gpx.haversine(a, b) >= activities.MIN_SPACING_M for a, b in zip(kept, kept[1:-1]))


def test_link_to_an_own_activity(client, myauth, acts):
    login(client, myauth)
    url = "https://connect.garmin.com/modern/activity/101"
    r = client.post("/routes/link", data={"url": url}, follow_redirects=False)
    assert r.status_code == 303
    route = only_route()
    assert route.name.startswith("Puchheim Laufen ") and route.name.endswith("hm")   # no place list
    assert route.sports == ["running"] and route.source == "garmin_activity"
    assert route.external_id == "101" and route.source_url == url
    assert "From the Garmin activity “Puchheim Laufen” on Nov 1, 2026." == route.description
    from app import store
    data = store.get(route.gpx_sha)
    assert b"<time>" not in data and b"hr>" not in data and b"<ele>" in data   # only the way
    again = client.post("/routes/link", data={"url": url})
    assert "This route is already here" in again.text


def test_a_foreign_private_activity_and_no_connection(client, myauth, acts):
    login(client, myauth)
    r = client.post("/routes/link", data={"url": "https://connect.garmin.com/modern/activity/900"})
    assert "Garmin does not share this activity with you" in r.text
    r = client.post("/routes/link", data={"url": "https://connect.garmin.com/modern/activity/103"})
    assert "multisport activity" in r.text
    login(client, myauth, uid=99, username="nobody")
    r = client.post("/routes/link", data={"url": "https://connect.garmin.com/modern/activity/101"})
    assert "Your Garmin account is not connected" in r.text


def test_the_page_lists_activities_with_gps_and_multisport_parts(client, myauth, acts):
    login(client, myauth)
    client.post("/routes/link", data={"url": "https://connect.garmin.com/modern/activity/101"})
    page = client.get("/routes/garmin").text
    assert "Puchheim Laufen" in page and "Rolle" not in page              # no GPS: not offered
    assert "Triathlon Rad" in page and "Triathlon Lauf" in page and "take its parts" in page
    assert 'value="104"' in page and 'value="105"' in page and 'value="103"' not in page
    assert "already taken over" in page and 'value="101"' not in page     # taken: no box
    assert page.count('value="104"') == 1                              # not twice


def test_filters_and_paging_go_to_garmin(client, myauth, acts, monkeypatch):
    login(client, myauth)
    monkeypatch.setattr(activities, "PAGE", 2)
    page = client.get("/routes/garmin?sport=running&from=2026-10-01&to=2026-11-01").text
    p = acts.list_params[-1]
    assert (p["activityType"], p["startDate"], p["endDate"], p["limit"]) == (
        "running", "2026-10-01", "2026-11-01", "2")
    assert "Older" in page and "start=2" in page
    client.get("/routes/garmin?sport=evil&from=yesterday")
    assert "activityType" not in acts.list_params[-1] and "startDate" not in acts.list_params[-1]


def test_take_several_at_once(client, myauth, acts):
    login(client, myauth)
    r = client.post("/routes/garmin", data={"ids": ["104", "105", "900"]})
    assert r.status_code == 200 and r.text.count("Added") == 2 and "does not share" in r.text
    with get_session() as s:
        names = sorted(x.sports[0] for x in s.exec(select(Route)))
    assert names == ["road_biking", "running"]
    one = client.post("/routes/garmin", data={"ids": ["101"]}, follow_redirects=False)
    assert one.status_code == 303 and one.headers["location"].startswith("/routes/")


def test_the_page_without_garmin(client, myauth, acts):
    login(client, myauth, uid=99, username="nobody")
    assert "Your Garmin account is not connected" in client.get("/routes/garmin").text


def test_add_route_offers_it(client):
    assert 'href="/routes/garmin"' in client.get("/routes/new").text
