"""Sending routes on to the user's devices - only when they tick them."""

import time

from sqlmodel import select

from app import garmin_sync, routes
from app.db import get_session
from app.models import GarminCourse, Route
from tests.conftest import USER, make_gpx

EDGE = {"deviceId": 101, "productDisplayName": "Edge 850", "courseCapable": True,
        "deviceCategories": ["FITNESS", "DEDICATED_BIKE_COMPUTER"]}
FENIX = {"deviceId": 202, "productDisplayName": "fenix 8 Pro", "courseCapable": True}
HRM = {"deviceId": 303, "productDisplayName": "HRM 600", "courseCapable": False}


def new_route(name="Ride", sports=("road_biking", "gravel_cycling")):
    with get_session() as s:
        return routes.create(s, make_gpx(name), sport_keys=list(sports), user=USER)


def login(client, myauth):
    myauth.body = dict(USER)
    client.cookies.set("sso_session", "x")


def wait_idle(uid=7):
    for _ in range(200):
        if not garmin_sync.run_state(uid).running:
            return
        time.sleep(0.02)
    raise AssertionError("still running")


def row():
    with get_session() as s:
        return s.exec(select(GarminCourse)).one()


def send(client, r, *devices, sport="road_biking", **extra):
    res = client.post("/garmin/send", data={"ids": r.id, f"sport_{r.id}": sport,
                                            "device": [str(d) for d in devices], **extra})
    wait_idle()
    return res


def test_nothing_goes_to_a_device_unless_ticked(client, myauth, garmin):
    garmin.devices = [EDGE, FENIX]
    login(client, myauth)
    send(client, new_route())
    assert len(garmin.accounts["tok7"]) == 1 and garmin.messages == []


def test_send_page_offers_only_course_capable_devices(client, myauth, garmin):
    garmin.devices = [EDGE, FENIX, HRM]
    login(client, myauth)
    page = client.get(f"/garmin/send?ids={new_route().id}").text
    assert 'name="device" value="101"> Edge 850' in page and "fenix 8 Pro" in page
    assert "HRM 600" not in page and 'name="all_devices"' in page
    assert "only you can remove them, on the device itself" in page


def test_send_to_devices_makes_the_course_first(client, myauth, garmin):
    garmin.devices = [EDGE, FENIX]
    login(client, myauth)
    r = new_route()
    client.get(f"/garmin/send?ids={r.id}")                    # learns the devices
    send(client, r, 101, sport="gravel_cycling")
    (cid, course), = garmin.accounts["tok7"].items()
    assert course["activityTypePk"] == 143
    msg, = garmin.messages
    assert (msg["deviceId"], msg["metaDataId"], msg["messageType"]) == (101, cid, "courses")
    assert msg["messageUrl"] == f"course-service/course/fit/{cid}/101?elevation=true"
    assert row().pushed_to == [101]
    assert "Devices: Edge 850" in client.get(f"/routes/{r.id}").text
    done = client.get(f"/garmin/send?ids={r.id}&sent=1").text
    assert "Also sent to Edge 850" in done


def test_send_to_all_devices(client, myauth, garmin):
    garmin.devices = [EDGE, FENIX]
    login(client, myauth)
    r = new_route()
    client.get(f"/garmin/send?ids={r.id}")
    send(client, r, all_devices="1")
    assert len(garmin.accounts["tok7"]) == 1
    assert sorted(m["deviceId"] for m in garmin.messages) == [101, 202]
    assert sorted(row().pushed_to) == [101, 202]


def test_a_changed_route_leaves_the_old_version_on_the_device(client, myauth, garmin):
    garmin.devices = [EDGE, FENIX]
    login(client, myauth)
    r = new_route()
    client.get(f"/garmin/send?ids={r.id}")
    send(client, r, 101, 202)
    with get_session() as s:
        route = s.get(Route, r.id)
        route.name = "Ride (new)"
        s.add(route)
        s.commit()
    send(client, r, 202)
    assert (row().pushed_to, row().pushed_old) == ([202], [101])
    assert "Edge 850 (old version)" in client.get("/garmin").text
    send(client, r, 101)                                       # up to date there too
    assert (sorted(row().pushed_to), row().pushed_old) == ([101, 202], [])


def test_unknown_device_is_refused(client, myauth, garmin):
    garmin.devices = [EDGE]
    login(client, myauth)
    r = new_route()
    client.get(f"/garmin/send?ids={r.id}")
    res = send(client, r, 999)
    assert res.status_code == 422 and garmin.messages == [] and not garmin.accounts.get("tok7")


BEN = {**USER, "uid": 8, "username": "ben", "display_name": "Ben"}
FORERUNNER = {"deviceId": 404, "productDisplayName": "Forerunner 965", "courseCapable": True}


def test_every_user_sees_and_uses_only_their_own_devices(client, myauth, garmin):
    garmin.devices = {"tok7": [EDGE, FENIX], "tok8": [FORERUNNER]}
    r = new_route()
    login(client, myauth)                                   # Anna
    page = client.get(f"/garmin/send?ids={r.id}").text
    assert "Edge 850" in page and "fenix 8 Pro" in page and "Forerunner" not in page
    with get_session() as s:                                # Ben, a copy of the route
        r = routes.share(s, r, BEN, USER)
        s.commit()
        s.refresh(r)
    myauth.body = dict(BEN)
    client.cookies.set("sso_session", "ben")
    page = client.get(f"/garmin/send?ids={r.id}").text
    assert "Forerunner 965" in page and "Edge 850" not in page and "fenix" not in page
    # Anna's device id is not Ben's to use
    assert client.post("/garmin/send", data={"ids": r.id, f"sport_{r.id}": "road_biking",
                                             "device": "101"}).status_code == 422
    client.post("/garmin/send", data={"ids": r.id, f"sport_{r.id}": "road_biking",
                                      "device": "404"})
    wait_idle(8)
    msg, = garmin.messages
    assert msg["deviceId"] == 404 and len(garmin.accounts["tok8"]) == 1
    assert garmin.accounts.get("tok7", {}) == {}           # nothing in Anna's account


def test_no_devices_is_not_asked_on_every_view(client, myauth, garmin):
    garmin.devices = []
    r = new_route()
    login(client, myauth)
    for _ in range(3):
        page = client.get(f"/garmin/send?ids={r.id}").text
    assert garmin.device_lookups == 1 and "No device that can take courses" in page


def test_my_garmin_keeps_the_device_list_current(client, myauth, garmin):
    garmin.devices = [EDGE]
    login(client, myauth)
    client.get("/garmin?fresh=1")
    garmin.devices = [EDGE, FENIX]
    client.get("/garmin?fresh=1")
    page = client.get(f"/garmin/send?ids={new_route().id}").text
    assert "fenix 8 Pro" in page
