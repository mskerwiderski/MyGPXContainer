"""Sending routes to Garmin Connect and removing them again, against a fake
Garmin account (garmin_courses._client) and a fake MyAuth
(access.myauth._fetch_garmin). Nothing goes on the network."""

import asyncio
import sqlite3
import time

import pytest
from sqlmodel import select

from app import auth, db, garmin_courses, garmin_sync, routes
from app.db import get_session
from app.models import GarminCourse, Route
from tests.conftest import USER, make_gpx

ANNA = {"uid": USER["uid"], "username": USER["username"]}


def new_route(name="Lake", lon=11.0, description="", sports=("gravel_cycling",), user=USER):
    with get_session() as s:
        return routes.create(s, make_gpx(name, lon=lon), description=description,
                             sport_keys=list(sports), user=user)


def send(*items, devices=(), user=ANNA):
    """items: routes (as their first sport) or (route, sport)."""
    pairs = [(i[0].uid, i[1]) if isinstance(i, tuple) else (i.uid, i.sports[0]) for i in items]
    return asyncio.run(garmin_sync.send(user["uid"], user["username"], pairs, list(devices)))


def remove(*row_ids, user=ANNA):
    return asyncio.run(garmin_sync.remove(user["uid"], user["username"], list(row_ids)))


def refresh(user=ANNA):
    asyncio.run(garmin_sync.refresh(user["uid"], user["username"]))


def rows():
    with get_session() as s:
        return s.exec(select(GarminCourse)).all()


def rename(route, name):
    with get_session() as s:
        r = s.get(Route, route.id)
        r.name = name
        s.add(r)
        s.commit()
        s.refresh(r)
        return r


def test_send_makes_a_private_marked_course_with_heights(garmin):
    route = new_route(description="Flat and fast")
    result = send(route)
    assert (result["routes"], result["failed"]) == (1, [])
    (cid, course), = garmin.accounts["tok7"].items()
    assert course["courseName"] == "Lake" and course["activityTypePk"] == 143
    assert course["rulePK"] == 2
    assert course["description"] == f"Flat and fast\n\nMGC:route={route.uid}"
    assert [p["elevation"] for p in course["geoPoints"]][:3] == [500, 501, 502]
    assert course["elevationGainMeter"] == route.ascent_m
    row, = rows()
    assert (row.course_id, row.name, row.synced_at is not None, row.error) == (cid, "Lake", True, "")
    with get_session() as s:
        assert garmin_sync.state(row, s.get(Route, route.id)) == "current"


def test_sending_an_unchanged_route_again_keeps_its_course(garmin):
    route = new_route()
    send(route)
    cid = rows()[0].course_id
    assert send(route)["routes"] == 1
    assert list(garmin.accounts["tok7"]) == [cid]


def test_a_changed_route_shows_as_changed_until_sent_again(garmin):
    route = new_route()
    send(route)
    old = rows()[0].course_id
    route = rename(route, "Lake (new)")
    assert garmin_sync.state(rows()[0], route) == "changed"
    assert list(garmin.accounts["tok7"]) == [old]            # nothing happens by itself
    send(route)
    (cid, course), = garmin.accounts["tok7"].items()
    assert cid != old and course["courseName"] == "Lake (new)"
    assert garmin_sync.state(rows()[0], route) == "current" and rows()[0].name == "Lake (new)"


def test_another_sport_replaces_the_course(garmin):
    route = new_route(sports=("road_biking", "gravel_cycling"))
    send((route, "road_biking"))
    send((route, "gravel_cycling"))
    (_, course), = garmin.accounts["tok7"].items()
    assert course["activityTypePk"] == 143 and rows()[0].activity_type == "gravel_cycling"


def test_a_deleted_route_keeps_its_course_until_removed(garmin):
    route = new_route()
    send(route)
    with get_session() as s:
        routes.delete(s, s.get(Route, route.id))
    row, = rows()
    assert garmin_sync.state(row, None) == "deleted" and len(garmin.accounts["tok7"]) == 1
    refresh()
    assert len(rows()) == 1                                   # still there in Garmin
    assert remove(row.id) == {"kind": "remove", "removed": 1, "failed": []}
    assert garmin.accounts["tok7"] == {} and rows() == []


def test_a_course_deleted_in_garmin_drops_out_and_is_not_made_again(garmin):
    keep, gone = new_route("Keep"), new_route("Gone", lon=12.0)
    send(keep, gone)
    by_name = {r.name: r.course_id for r in rows()}
    del garmin.accounts["tok7"][by_name["Gone"]]
    refresh()
    assert [r.name for r in rows()] == ["Keep"]
    assert len(garmin.accounts["tok7"]) == 1
    send(gone)                                                # sending again makes it anew
    assert len(garmin.accounts["tok7"]) == 2


def test_refresh_names_a_deleted_route_from_garmin(garmin):
    route = new_route()
    send(route)
    with get_session() as s:
        row = s.exec(select(GarminCourse)).one()
        row.name = ""                                        # as the migration leaves it
        s.add(row)
        routes.delete(s, s.get(Route, route.id))
        s.commit()
    refresh()
    assert rows()[0].name == "Lake"


def test_a_course_without_our_mark_is_never_deleted(garmin):
    send(new_route())
    row, = rows()
    garmin.accounts["tok7"][row.course_id]["description"] = "edited by the user in Garmin"
    result = remove(row.id)
    left = "Changed in Garmin Connect, so it was left there - delete it there."
    assert result["failed"] == [("Lake", left)]
    assert row.course_id in garmin.accounts["tok7"] and rows() == []


def test_remove_waits_while_garmin_is_not_ready(garmin):
    send(new_route())
    garmin.busy_deletes = 2
    assert remove(rows()[0].id)["removed"] == 1 and garmin.accounts["tok7"] == {}
    assert garmin.waited == 2 * garmin_courses.DELETE_WAIT_S


def test_remove_gives_up_and_keeps_the_row(garmin):
    send(new_route())
    row, = rows()
    garmin.busy_deletes = garmin_courses.DELETE_TRIES
    result = remove(row.id)
    assert result["removed"] == 0 and "still processing" in result["failed"][0][1]
    assert "still processing" in rows()[0].error and len(garmin.accounts["tok7"]) == 1
    assert remove(row.id)["removed"] == 1 and garmin.accounts["tok7"] == {}


def test_each_user_only_touches_their_own_account(garmin):
    ben = {"uid": 8, "username": "ben"}
    route = new_route()
    with get_session() as s:
        copy = routes.share(s, route, ben, USER)
        s.commit()
        s.refresh(copy)
    send(route)
    assert {t for t, _, _ in garmin.calls} == {"tok7"}
    assert send(route, user=ben)["routes"] == 0               # not his route
    send(copy, user=ben)
    assert len(garmin.accounts["tok8"]) == 1 and len(garmin.accounts["tok7"]) == 1
    annas, = [r for r in rows() if r.uid == 7]
    remove(annas.id, user=ben)                                # not his row
    assert len(garmin.accounts["tok7"]) == 1


def test_errors_are_reported_per_route(garmin):
    route = new_route()
    garmin.fail_create = True
    result = send(route)
    assert result["routes"] == 0 and "HTTP 500" in result["failed"][0][1]
    assert rows() == []                                       # nothing is in Garmin
    garmin.fail_create = False
    assert send(route)["routes"] == 1


def test_not_connected(garmin):
    with pytest.raises(auth.GarminUnavailable):
        send(new_route(), user={"uid": 99, "username": "nobody"})


def test_migration_turns_marks_into_courses(garmin):
    """v0.17.0: a row was a wish, now it is a course that is there."""
    there, waiting = new_route("There"), new_route("Waiting", lon=12.0)
    gone = new_route("Gone", lon=13.0)
    send(there, gone)
    with get_session() as s:
        routes.delete(s, s.get(Route, gone.id))
    path = db.get_engine().url.database
    db.get_engine().dispose()
    con = sqlite3.connect(path)                     # back to the shape before v0.17.0
    for col in ("name", "pushed_old"):
        con.execute(f"ALTER TABLE garmincourse DROP COLUMN {col}")
    con.execute("ALTER TABLE garmincourse ADD COLUMN wanted BOOLEAN NOT NULL DEFAULT 1")
    con.execute("UPDATE garmincourse SET wanted = 0 WHERE route_uid = ?", (gone.uid,))
    con.execute("INSERT INTO garmincourse (uid, username, route_uid, activity_type, synced_hash, "
                "error, pushed_to, wanted) VALUES (7, 'anna', ?, 'gravel_cycling', '', '', '[]', 1)",
                (waiting.uid,))                     # marked, never sent
    con.commit()
    con.close()
    db._engine = None
    db.get_engine()
    db._migrate(db.get_engine())                    # a second run changes nothing
    assert sorted((r.route_uid, r.name) for r in rows()) == sorted(
        [(there.uid, "There"), (gone.uid, "")])
    refresh()
    assert sorted(r.name for r in rows()) == ["Gone", "There"]


# ---------- pages ----------

def login(client, myauth, **user):
    myauth.body = {**USER, **user}
    client.cookies.set("sso_session", "x" + str(user))


def wait_idle(uid=7):
    for _ in range(200):
        if not garmin_sync.run_state(uid).running:
            return
        time.sleep(0.02)
    raise AssertionError("still running")


def test_send_and_remove_from_the_route_page(client, myauth, garmin):
    login(client, myauth)
    route = new_route()
    page = client.get(f"/routes/{route.id}").text
    assert f"/garmin/send?ids={route.id}&amp;back=/routes/{route.id}" in page
    form = client.get(f"/garmin/send?ids={route.id}&back=/routes/{route.id}").text
    assert f'name="sport_{route.id}" value="gravel_cycling"' in form     # its only sport
    r = client.post("/garmin/send", data={"ids": route.id, f"sport_{route.id}": "gravel_cycling",
                                          "back": f"/routes/{route.id}"})
    assert r.status_code == 200 and "data-sync-running" in r.text
    wait_idle()
    assert len(garmin.accounts["tok7"]) == 1
    done = client.get(f"/garmin/send?ids={route.id}&back=/routes/{route.id}&sent=1").text
    assert "1 routes in Garmin Connect." in done
    page = client.get(f"/routes/{route.id}").text
    assert "In Garmin Connect" in page and "Remove from Garmin Connect" in page
    assert ">G</span>" in client.get("/").text
    assert "Lake" in client.get("/garmin").text
    r = client.post("/garmin/remove", data={"ids": rows()[0].id, "back": f"/routes/{route.id}"},
                    follow_redirects=False)
    assert r.headers["location"] == f"/routes/{route.id}"
    wait_idle()
    assert garmin.accounts["tok7"] == {} and rows() == []


def test_send_several_from_the_list(client, myauth, garmin):
    login(client, myauth)
    a = new_route("A", sports=("road_biking", "gravel_cycling"))
    b = new_route("B", lon=12.0, sports=())
    r = client.post("/routes/bulk", data={"action": "garmin", "ids": [a.id, b.id], "back": "q=x"},
                    follow_redirects=False)
    assert r.headers["location"] == f"/garmin/send?ids={a.id}&ids={b.id}&back=%2F%3Fq%3Dx"
    form = client.get(r.headers["location"]).text
    assert f'<select id="sport_{a.id}"' in form and f'<select id="sport_{b.id}"' in form
    assert 'value="road_biking" selected' in form          # A's first sport
    client.post("/garmin/send", data={"ids": [a.id, b.id], f"sport_{a.id}": "gravel_cycling",
                                      f"sport_{b.id}": "hiking"})
    wait_idle()
    assert sorted(c["activityTypePk"] for c in garmin.accounts["tok7"].values()) == sorted(
        [143, garmin_sync.BY_KEY["hiking"].type_id])


def test_my_garmin_removes_the_picked_or_all(client, myauth, garmin):
    login(client, myauth)
    a, b, c = new_route("A"), new_route("B", lon=12.0), new_route("C", lon=13.0)
    send(a, b, c)
    with get_session() as s:
        routes.delete(s, s.get(Route, c.id))
    page = client.get("/garmin").text
    assert page.count('name="ids"') == 3 and "Route deleted" in page and ">C</td>" in page
    assert "only you can remove them, on the device itself" in page
    ids = {r.name: r.id for r in rows()}
    client.post("/garmin/remove", data={"ids": [ids["A"], 12345]})   # a foreign id: ignored
    wait_idle()
    assert sorted(r.name for r in rows()) == ["B", "C"]
    assert "1 removed from Garmin Connect." in client.get("/garmin").text
    client.post("/garmin/remove", data={"all": "1"})
    wait_idle()
    assert rows() == [] and garmin.accounts["tok7"] == {}
    assert "Nothing in Garmin Connect yet" in client.get("/garmin").text


def test_unknown_sport_is_refused(client, myauth, garmin):
    login(client, myauth)
    route = new_route()
    r = client.post("/garmin/send", data={"ids": route.id, f"sport_{route.id}": "x"})
    assert r.status_code == 422 and rows() == []


def test_someone_elses_route_cannot_be_sent(client, myauth, garmin):
    bens = new_route(user={**USER, "uid": 8, "username": "ben"})
    login(client, myauth)
    assert client.get(f"/garmin/send?ids={bens.id}").status_code == 404
    r = client.post("/garmin/send", data={"ids": bens.id, f"sport_{bens.id}": "gravel_cycling"})
    assert r.status_code == 404 and garmin.accounts == {}


def test_garmin_needs_a_login(client):
    with get_session() as s:                # without login: a route without an owner
        route = routes.create(s, make_gpx("Lake"), sport_keys=["gravel_cycling"])
    assert "Sign in to send routes" in client.get(f"/routes/{route.id}").text
    assert client.get(f"/garmin/send?ids={route.id}").status_code == 403
    assert client.post("/garmin/send", data={"ids": route.id}).status_code == 403
    assert client.post("/garmin/remove", data={"all": "1"}).status_code == 403
    assert client.get("/garmin").status_code == 403


def test_garmin_page_shows_a_missing_connection(client, myauth, garmin):
    login(client, myauth, uid=99, username="nobody")
    assert "not connected" in client.get("/garmin?fresh=1").text


def test_my_garmin_comes_at_once_and_asks_garmin_afterwards(client, myauth, garmin):
    login(client, myauth)
    send(new_route())
    garmin.calls.clear()
    page = client.get("/garmin").text
    assert garmin.calls == []                                 # nothing asked yet
    assert "Checking Garmin Connect…" in page and 'data-check-url="/garmin?fresh=1"' in page
    assert "Lake" in page                                     # what we know already
    fresh = client.get("/garmin?fresh=1").text
    assert garmin.calls and "data-check-url" not in fresh and "Checking" not in fresh
