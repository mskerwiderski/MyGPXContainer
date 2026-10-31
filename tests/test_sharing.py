"""Routes per user, shared as copies (v0.11.0, Michael 2026-10-29): who can be
picked comes from MyAuth (auth.myauth._fetch_members), the copy is the receiver's own."""

import asyncio
import sqlite3

import pytest
from sqlmodel import select

from app import config, db, garmin_sync, routes, store
from app.access import myauth as access_myauth
from app.auth import myauth as auth_myauth
from app.db import get_session
from app.models import Folder, GarminCourse, Route
from tests.conftest import USER, make_gpx

ANNA = USER
BEN = {**USER, "uid": 8, "username": "ben", "display_name": "Ben"}
CARL = {**USER, "uid": 9, "username": "carl", "display_name": "Carl"}


@pytest.fixture
def people(monkeypatch, myauth):
    """MyAuth lists Anna, Ben and Carl as the users of the app."""
    monkeypatch.setenv("MYAUTH_APP_KEY", "secret")
    monkeypatch.setattr(config, "_settings", None)

    class Fake:
        status = 200
        body = {"members": [{k: u[k] for k in ("uid", "username", "display_name")}
                            for u in (ANNA, BEN, CARL)]}
        asked: list[int] = []

    async def fetch(uid):
        Fake.asked.append(uid)
        if Fake.status is None:
            raise access_myauth.Unavailable("down")
        return Fake.status, Fake.body
    monkeypatch.setattr(auth_myauth, "_fetch_members", fetch)
    return Fake


def login(client, myauth, user):
    myauth.body = dict(user)
    client.cookies.set("sso_session", "s-" + user["username"])


def upload(client, name, lon=11.0, sports=("road_biking",)):
    r = client.post("/routes", files=[("files", (f"{name}.gpx", make_gpx(name, lon=lon),
                                                 "application/gpx+xml"))],
                    data={"sports": list(sports)}, follow_redirects=False)
    return int(r.headers["location"].rsplit("/", 1)[1])


def all_routes():
    with get_session() as s:
        return s.exec(select(Route).order_by(Route.id)).all()


def share(client, ids, to, back=""):
    return client.post("/routes/share", data={"ids": [str(i) for i in ids],
                                              "to": [str(t) for t in to], "back": back})


def test_share_a_route_gives_a_copy_of_their_own(client, myauth, people):
    login(client, myauth, ANNA)
    rid = upload(client, "Lake", sports=("road_biking", "gravel_cycling"))
    detail = client.get(f"/routes/{rid}").text
    assert f"/routes/share?ids={rid}&amp;back=/routes/{rid}" in detail
    page = client.get(f"/routes/share?ids={rid}&back=/routes/{rid}").text
    assert 'value="8"> Ben' in page and 'value="9"> Carl' in page and 'value="7"' not in page
    assert f'class="back" href="/routes/{rid}" data-back="/routes/{rid}"' in page
    r = share(client, [rid], [8], back=f"/routes/{rid}")
    assert r.status_code == 200 and "Ben: 1 shared" in r.text

    orig, copy = all_routes()
    assert (copy.created_by_uid, copy.created_by_username, copy.created_by_name) == (8, "ben", "Ben")
    assert (copy.shared_by_uid, copy.shared_by_username, copy.shared_by_name) == (
        7, "anna", "Anna Muster")
    assert copy.shared_from == orig.uid and copy.uid != orig.uid and copy.shared_at
    assert (copy.name, copy.sports, copy.gpx_sha, copy.distance_m, copy.folder_id) == (
        orig.name, orig.sports, orig.gpx_sha, orig.distance_m, None)

    again = share(client, [rid], [8, 9])
    assert "Ben: 0 shared · 1 already there" in again.text and "Carl: 1 shared" in again.text
    assert len(all_routes()) == 3
    assert people.asked == [7]                      # asked as Anna, once (cached)


def test_the_copy_is_theirs_to_change(client, myauth, people):
    login(client, myauth, ANNA)
    rid = upload(client, "Lake")
    share(client, [rid], [8])
    copy = all_routes()[1]
    login(client, myauth, BEN)
    page = client.get("/").text
    assert ">Lake</a>" in page and "Shared by Anna Muster" in page and 'name="by"' in page
    assert ">Lake</a>" in client.get("/?by=anna").text and ">Lake</a>" not in client.get("/?by=me").text
    assert "Shared by Anna Muster on" in client.get(f"/routes/{copy.id}").text
    client.post(f"/routes/{copy.id}/edit", data={"name": "Bens Lake", "sports": ["hiking"]})
    orig, copy = all_routes()
    assert (orig.name, orig.sports) == ("Lake", ["road_biking"])
    assert (copy.name, copy.sports) == ("Bens Lake", ["hiking"])
    client.post(f"/routes/{copy.id}/delete")
    assert len(all_routes()) == 1 and store.get(orig.gpx_sha) == make_gpx("Lake")
    login(client, myauth, ANNA)                     # Anna's route never noticed
    assert client.get(f"/routes/{rid}").status_code == 200


def test_only_people_myauth_lists_and_never_oneself(client, myauth, people):
    login(client, myauth, ANNA)
    rid = upload(client, "Lake")
    for to in ([42], [7], []):
        r = share(client, [rid], to)
        assert r.status_code == 422 and "Pick at least one person." in r.text
        assert 'value="8"> Ben' in r.text           # the form is there again
    assert len(all_routes()) == 1


def test_only_own_routes_can_be_shared(client, myauth, people):
    login(client, myauth, BEN)
    bens = upload(client, "Bens")
    login(client, myauth, ANNA)
    rid = upload(client, "Lake", lon=12.0)
    assert share(client, [bens], [9]).status_code == 404
    r = share(client, [rid, bens], [9])             # Ben's id is left out
    assert "Carl: 1 shared" in r.text and len(all_routes()) == 3


def test_when_myauth_cannot_tell(client, myauth, people):
    login(client, myauth, ANNA)
    rid = upload(client, "Lake")
    people.status = None                            # MyAuth down
    assert "MyAuth is not reachable right now." in client.get(f"/routes/share?ids={rid}").text
    r = share(client, [rid], [8])
    assert r.status_code == 503 and len(all_routes()) == 1
    auth_myauth.clear_cache()
    people.status, people.body = 403, {"detail": "not_allowed"}     # flag missing in MyAuth
    page = client.get(f"/routes/share?ids={rid}").text
    assert "MyAuth does not list the users of MyGPXContainer." in page and 'name="to"' not in page


def test_nobody_else_yet(client, myauth, people):
    people.body = {"members": [{"uid": 7, "username": "anna", "display_name": "Anna Muster"}]}
    login(client, myauth, ANNA)
    rid = upload(client, "Lake")
    assert "Nobody else uses MyGPXContainer yet." in client.get(f"/routes/share?ids={rid}").text


def test_without_login_no_share_button(client):
    with get_session() as s:
        route = routes.create(s, make_gpx("Lake"))
    page = client.get(f"/routes/{route.id}").text
    assert "/routes/share" not in page
    assert "Sharing is not available here." in client.get(f"/routes/share?ids={route.id}").text


def test_share_several_from_the_selection(client, myauth, people):
    login(client, myauth, ANNA)
    a, b = upload(client, "A"), upload(client, "B", lon=12.0)
    r = client.post("/routes/bulk", data={"action": "share", "ids": [str(a), str(b)],
                                          "back": "q=x"}, follow_redirects=False)
    assert r.headers["location"] == f"/routes/share?ids={a}&ids={b}&back=%2F%3Fq%3Dx"
    page = client.get(r.headers["location"]).text
    assert ">A</a>" in page and ">B</a>" in page
    assert 'class="back" href="/?q=x" data-back="/"' in page
    assert "Ben: 2 shared" in share(client, [a, b], [8], back="/?q=x").text
    assert 'value="share"' in client.get("/").text          # the button in the selection bar


def test_back_must_stay_on_this_site(client, myauth, people):
    login(client, myauth, ANNA)
    rid = upload(client, "Lake")
    page = client.get(f"/routes/share?ids={rid}&back=//evil.example/x").text
    assert "evil.example" not in page and f'href="/routes/{rid}"' in page


def test_same_tour_is_already_there():
    with get_session() as s:
        orig = routes.create(s, make_gpx("Tour"), user=ANNA, source="komoot", external_id="123")
        routes.create(s, make_gpx("Tour v2", lon=12.0), user=BEN, source="komoot",
                      external_id="123")
        assert routes.share(s, orig, BEN, ANNA) is None
        assert routes.share(s, orig, CARL, ANNA) is not None


# ---------- Garmin: copies, and courses made before v0.11.0 ----------

def test_course_with_the_mark_of_the_original_is_still_removed(garmin):
    """A row moved to the user's copy while the course in Garmin still carries
    the uid of the route it was made from (the v0.11.0 migration does that)."""
    with get_session() as s:
        orig = routes.create(s, make_gpx("Lake"), sport_keys=["gravel_cycling"], user=ANNA)
        copy = routes.share(s, orig, BEN, ANNA)
        s.commit()
        s.refresh(copy)
    send = garmin_sync.send(8, "ben", [(orig.uid, "gravel_cycling")], [])
    assert asyncio.run(send)["routes"] == 0                   # not his route any more
    asyncio.run(garmin_sync.send(8, "ben", [(copy.uid, "gravel_cycling")], []))
    (cid, course), = garmin.accounts["tok8"].items()
    course["courseDescription"] = garmin_sync.mark(orig.uid)  # the old mark
    with get_session() as s:
        row = s.exec(select(GarminCourse)).one()
    assert asyncio.run(garmin_sync.remove(8, "ben", [row.id]))["removed"] == 1
    assert garmin.accounts["tok8"] == {}


def test_migration_splits_routes_and_folders_by_owner(tmp_path, monkeypatch):
    with get_session() as s:
        annas_alps = Folder(name="Alps", created_by_uid=7, created_by_username="anna")
        s.add(annas_alps)
        s.commit()
        a = routes.create(s, make_gpx("A"), user=ANNA, folder_id=annas_alps.id,
                          sport_keys=["road_biking"])
        routes.create(s, make_gpx("B", lon=12.0), user=BEN, folder_id=annas_alps.id)
        h = garmin_sync.route_hash(a, "road_biking")
        s.add_all([
            GarminCourse(uid=7, username="anna", route_uid=a.uid, activity_type="road_biking",
                         course_id=1, synced_hash=h),
            GarminCourse(uid=8, username="ben", route_uid=a.uid, activity_type="road_biking",
                         course_id=2, synced_hash=h)])
        s.commit()
    path = db.get_engine().url.database
    db.get_engine().dispose()
    con = sqlite3.connect(path)                     # back to the shape before v0.11.0
    for col in ("shared_by_uid", "shared_by_username", "shared_by_name", "shared_from",
                "shared_at"):
        con.execute(f"ALTER TABLE route DROP COLUMN {col}")
    con.commit()
    con.close()
    monkeypatch.setattr(db, "_engine", None)
    db.get_engine()
    db._migrate(db.get_engine())                    # a second run changes nothing

    with get_session() as s:
        rs = {(r.name, r.created_by_username): r for r in s.exec(select(Route))}
        assert sorted(rs) == [("A", "anna"), ("A", "ben"), ("B", "ben")]
        copy = rs[("A", "ben")]
        assert (copy.created_by_uid, copy.created_by_name, copy.folder_id) == (8, "Ben", None)
        assert (copy.shared_by_username, copy.shared_by_name, copy.shared_from) == (
            "anna", "Anna Muster", a.uid)
        assert copy.gpx_sha == a.gpx_sha and copy.uid != a.uid
        assert copy.created_at == rs[("A", "anna")].created_at      # keeps its place in the list
        rows = {r.username: r for r in s.exec(select(GarminCourse))}
        assert rows["anna"].route_uid == a.uid and rows["ben"].route_uid == copy.uid
        assert garmin_sync.state(rows["ben"], copy) == "current"    # nothing to rebuild
        folders = {(f.name, f.created_by_username): f.id for f in s.exec(select(Folder))}
        assert sorted(folders) == [("Alps", "anna"), ("Alps", "ben")]
        assert rs[("B", "ben")].folder_id == folders[("Alps", "ben")]
        assert rs[("A", "anna")].folder_id == folders[("Alps", "anna")]
