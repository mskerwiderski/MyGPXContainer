import re

from sqlmodel import select

from app import store
from app.db import get_session
from app.models import Route
from tests.conftest import USER, make_gpx


def upload(client, *files, sports=(), description=""):
    return client.post("/routes", files=[("files", (n, d, "application/gpx+xml")) for n, d in files],
                       data={"sports": list(sports), "description": description},
                       follow_redirects=False)


def all_routes():
    with get_session() as s:
        return s.exec(select(Route)).all()


def test_upload_one_file_opens_the_route(client):
    r = upload(client, ("lake.gpx", make_gpx("Lake")), sports=["gravel_cycling", "nonsense",
                                                                  "hiking"])
    assert r.status_code == 303
    route = all_routes()[0]
    assert r.headers["location"] == f"/routes/{route.id}"
    assert route.name == "Lake" and route.sports == ["hiking", "gravel_cycling"]
    # 19 steps of 1 m: the 4 m hysteresis counts 16 (the last 3 m never add up)
    assert route.ascent_m == 16 and route.point_count == 20 and not route.loop
    # no elevation model here (conftest): the file stays as it came
    assert store.get(route.gpx_sha) == make_gpx("Lake") and route.elevation_source == "kept"


def test_name_falls_back_to_file_name(client):
    data = make_gpx("").replace(b"<name></name>", b"")
    upload(client, ("Isar Trail.gpx", data))
    assert all_routes()[0].name == "Isar Trail"


def test_upload_several_files_reports_each(client):
    upload(client, ("a.gpx", make_gpx("A")))
    r = upload(client, ("a-again.gpx", make_gpx("A")), ("b.gpx", make_gpx("B", lon=12.0)),
               ("bad.gpx", b"<html/>"))
    assert r.status_code == 200
    assert "Already there" in r.text and "Added" in r.text and "not a valid GPX file" in r.text
    assert sorted(x.name for x in all_routes()) == ["A", "B"]


def test_list_and_detail(client):
    upload(client, ("lake.gpx", make_gpx("Lake")), sports=["running"])
    route = all_routes()[0]
    page = client.get("/").text
    assert f'href="/routes/{route.id}"' in page and "Running" in page and "2.1 km" in page
    detail = client.get(f"/routes/{route.id}").text
    assert '<script type="application/json" id="track">{"line":[[48.0,11.0]' in detail
    assert "Download GPX" in detail and f"/routes/{route.id}/edit" in detail


def test_download_keeps_the_original_bytes(client):
    upload(client, ("x.gpx", make_gpx("Über den Berg")))
    route = all_routes()[0]
    r = client.get(f"/routes/{route.id}/gpx")
    assert r.content == make_gpx("Über den Berg")
    assert 'filename="Uber_den_Berg.gpx"' in r.headers["content-disposition"]


def test_missing_route_is_404(client):
    assert client.get("/routes/99").status_code == 404


def test_edit_and_replace_file(client):
    upload(client, ("x.gpx", make_gpx("Old")))
    route = all_routes()[0]
    old_sha = route.gpx_sha
    r = client.post(f"/routes/{route.id}/edit",
                    data={"name": "New", "description": "Gravel all the way", "sports": ["cycling"]},
                    files={"file": ("y.gpx", make_gpx("Y", n=40), "application/gpx+xml")},
                    follow_redirects=False)
    assert r.status_code == 303
    route = all_routes()[0]
    assert (route.name, route.description, route.sports) == ("New", "Gravel all the way",
                                                              ["cycling"])
    assert route.point_count == 40 and route.gpx_sha != old_sha
    assert not (store._path(old_sha)).exists()


def test_edit_with_a_bad_file_changes_nothing(client):
    upload(client, ("x.gpx", make_gpx("Old")))
    route = all_routes()[0]
    r = client.post(f"/routes/{route.id}/edit", data={"name": "New"},
                    files={"file": ("y.gpx", b"nope", "application/gpx+xml")})
    assert r.status_code == 422 and "not a valid GPX file" in r.text
    assert all_routes()[0].name == "Old"


def test_edit_with_the_file_of_another_route(client):
    upload(client, ("a.gpx", make_gpx("A")))
    upload(client, ("b.gpx", make_gpx("B", lon=12.0)))
    b = [x for x in all_routes() if x.name == "B"][0]
    r = client.post(f"/routes/{b.id}/edit", data={"name": "B"},
                    files={"file": ("a.gpx", make_gpx("A"), "application/gpx+xml")})
    assert r.status_code == 422 and "is already the route “A”" in r.text


def test_delete_removes_route_and_file(client):
    upload(client, ("x.gpx", make_gpx("X")))
    route = all_routes()[0]
    r = client.post(f"/routes/{route.id}/delete", follow_redirects=False)
    assert r.status_code == 303 and all_routes() == []
    assert not store._path(route.gpx_sha).exists()


# ---------- permissions (login on) ----------

def login(client, myauth, **user):
    myauth.body = {**USER, **user}
    client.cookies.set("sso_session", "s-" + str(user.get("uid", USER["uid"])) +
                       str(user.get("app_admin", "")) + user.get("username", ""))


def test_owner_is_recorded(client, myauth):
    login(client, myauth)
    upload(client, ("x.gpx", make_gpx("X")))
    route = all_routes()[0]
    assert (route.created_by_uid, route.created_by_username, route.created_by_name) == (
        7, "anna", "Anna Muster")
    assert "Added on" in client.get(f"/routes/{route.id}").text


def _invisible(client, route):
    """Someone else's route: 404 everywhere, as if it did not exist."""
    assert ">X</a>" not in client.get("/").text
    for path in ("", "/edit", "/gpx"):
        assert client.get(f"/routes/{route.id}{path}").status_code == 404
    assert client.post(f"/routes/{route.id}/edit", data={"name": "Mine"}).status_code == 404
    assert client.post(f"/routes/{route.id}/delete").status_code == 404
    assert client.get(f"/garmin/send?ids={route.id}").status_code == 404
    assert client.get(f"/routes/share?ids={route.id}").status_code == 404
    assert all_routes()[0].name == "X"


def test_others_see_nothing(client, myauth):
    login(client, myauth)
    upload(client, ("x.gpx", make_gpx("X")))
    route = all_routes()[0]
    login(client, myauth, uid=8, username="ben", display_name="Ben")
    _invisible(client, route)


def test_reused_uid_is_not_the_owner(client, myauth):
    login(client, myauth)
    upload(client, ("x.gpx", make_gpx("X")))
    route = all_routes()[0]
    login(client, myauth, username="someone-else")      # same uid 7, rebuilt MyAuth
    _invisible(client, route)


def test_app_admin_sees_only_their_own_too(client, myauth):
    login(client, myauth)
    upload(client, ("x.gpx", make_gpx("X")))
    route = all_routes()[0]
    login(client, myauth, uid=8, username="ben", app_admin=True)
    _invisible(client, route)


def test_the_same_file_is_a_duplicate_only_for_the_same_user(client, myauth):
    login(client, myauth)
    upload(client, ("x.gpx", make_gpx("X")))
    login(client, myauth, uid=8, username="ben", display_name="Ben")
    r = upload(client, ("x.gpx", make_gpx("X")))
    assert r.status_code == 303                               # Ben's own route
    assert r.headers["location"] == f"/routes/{all_routes()[1].id}"
    assert "Already there" in upload(client, ("x.gpx", make_gpx("X")), ("y.gpx", make_gpx("Y"))).text
    anna, ben = all_routes()[:2]
    assert anna.gpx_sha == ben.gpx_sha                        # stored once
    client.post(f"/routes/{ben.id}/delete")
    assert store.get(anna.gpx_sha) == make_gpx("X")           # still Anna's


def test_german_numbers_and_sports(client, myauth):
    login(client, myauth, language="de")
    upload(client, ("x.gpx", make_gpx("X", n=200)), sports=["hiking"])
    page = client.get("/").text
    assert "Wandern" in page and re.search(r"22,1 km", page)


def test_list_shows_only_own_routes_all_with_swipe_delete(client, myauth):
    login(client, myauth)
    upload(client, ("a.gpx", make_gpx("Mine")))
    login(client, myauth, uid=8, username="ben", display_name="Ben")
    upload(client, ("b.gpx", make_gpx("Bens", lon=12.0)))
    mine = [r for r in all_routes() if r.name == "Bens"][0]
    page = client.get("/").text
    assert ">Bens</a>" in page and ">Mine</a>" not in page and "1 routes" in page
    assert f'data-swipe-delete="/routes/{mine.id}/delete"' in page
    assert page.count('class="danger swipe-del"') == 1


def test_back_links(client):
    upload(client, ("x.gpx", make_gpx("X")))
    route = all_routes()[0]
    assert 'class="back" href="/" data-back="/"' in client.get(f"/routes/{route.id}").text
    edit = client.get(f"/routes/{route.id}/edit").text
    assert f'class="back" href="/routes/{route.id}" data-back="/routes/{route.id}"' in edit
    assert 'class="back" href="/"' in client.get("/routes/new").text
