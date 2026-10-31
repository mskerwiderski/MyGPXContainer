import asyncio
import sqlite3

from sqlmodel import select

from app import config, db, garmin_sync, store
from app.db import get_session
from app.models import Folder, GarminCourse, Route
from tests.conftest import USER, make_gpx


def upload(client, name, lon=11.0, sports=("road_biking",), folder=""):
    client.post("/routes", files=[("files", (f"{name}.gpx", make_gpx(name, lon=lon),
                                             "application/gpx+xml"))],
                data={"sports": list(sports), "folder": folder})


def by_name(name):
    with get_session() as s:
        return s.exec(select(Route).where(Route.name == name)).one()


def folder_id(name):
    with get_session() as s:
        return s.exec(select(Folder).where(Folder.name == name)).one().id


def login(client, myauth, **user):
    myauth.body = {**USER, **user}
    client.cookies.set("sso_session", "f" + str(sorted(user.items())))


# ---------- folders ----------

def test_create_rename_delete_folder(client):
    assert client.post("/folders", data={"name": "  Fuerte  ventura "}).status_code == 200
    fid = folder_id("Fuerte ventura")
    upload(client, "A", folder=str(fid))
    assert by_name("A").folder_id == fid
    client.post(f"/folders/{fid}/rename", data={"name": "Fuerteventura"})
    assert folder_id("Fuerteventura") == fid
    page = client.get("/folders").text
    assert "Fuerteventura" in page and "General" in page
    client.post(f"/folders/{fid}/delete")
    assert by_name("A").folder_id is None          # back in the default folder


def test_folder_names_must_be_unique_and_present(client):
    client.post("/folders", data={"name": "Alps"})
    assert "already a folder with this name" in client.post("/folders", data={"name": "alps"}).text
    assert "needs a name" in client.post("/folders", data={"name": "   "}).text


def test_unknown_folder_id_means_the_default_folder(client):
    upload(client, "A", folder="999")
    assert by_name("A").folder_id is None


def test_folder_filter_and_counts(client):
    client.post("/folders", data={"name": "Alps"})
    fid = folder_id("Alps")
    upload(client, "Inside", folder=str(fid))
    upload(client, "Outside", lon=12.0)
    page = client.get(f"/?folder={fid}").text
    assert ">Inside</a>" in page and ">Outside</a>" not in page
    assert f'data-folder="{fid}">Alps <span>1</span>' in page
    default = client.get("/?folder=0").text
    assert ">Outside</a>" in default and ">Inside</a>" not in default


def test_edit_moves_a_route(client):
    client.post("/folders", data={"name": "Alps"})
    upload(client, "A")
    r = by_name("A")
    client.post(f"/routes/{r.id}/edit", data={"name": "A", "folder": str(folder_id("Alps"))})
    assert by_name("A").folder_id == folder_id("Alps")
    assert "▸ Alps" in client.get(f"/routes/{r.id}").text


def test_folders_are_each_users_own(client, myauth):
    login(client, myauth)
    client.post("/folders", data={"name": "Alps"})
    fid = folder_id("Alps")
    for who in ({"uid": 8, "username": "ben"}, {"uid": 8, "username": "ben", "app_admin": True}):
        login(client, myauth, **who)
        assert "Alps" not in client.get("/folders").text and "Alps" not in client.get("/").text
        assert client.post(f"/folders/{fid}/rename", data={"name": "Bens"}).status_code == 404
        assert client.post(f"/folders/{fid}/delete").status_code == 404
    upload(client, "Bens", folder=str(fid))                 # not his folder: the default one
    assert by_name("Bens").folder_id is None
    client.post("/folders", data={"name": "alps"})          # the name is free for him
    with get_session() as s:
        assert len(s.exec(select(Folder)).all()) == 2
    login(client, myauth)
    assert folder_id("Alps") == fid


def test_old_database_gets_the_folder_column(tmp_path, monkeypatch):
    data = tmp_path / "old"
    data.mkdir()
    con = sqlite3.connect(data / "mygpxcontainer.db")
    con.execute("CREATE TABLE route (id INTEGER PRIMARY KEY, uid TEXT, name TEXT)")
    con.commit()
    con.close()
    monkeypatch.setenv("MGC_DATA_DIR", str(data))
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(db, "_engine", None)
    with db.get_engine().connect() as c:
        cols = [r[1] for r in c.exec_driver_sql("PRAGMA table_info(route)")]
    assert "folder_id" in cols


# ---------- selection: bulk actions ----------

def bulk(client, action, *names, folder="", back=""):
    ids = [str(by_name(n).id) for n in names]
    return client.post("/routes/bulk", data={"action": action, "ids": ids, "folder": folder,
                                             "back": back}, follow_redirects=False)


def test_bulk_move_only_own_routes(client, myauth):
    login(client, myauth)
    upload(client, "Mine")
    login(client, myauth, uid=8, username="ben")
    upload(client, "Bens", lon=12.0)
    client.post("/folders", data={"name": "Alps"})
    fid = folder_id("Alps")
    r = bulk(client, "move", "Mine", "Bens", folder=str(fid), back="q=x")
    assert r.headers["location"] == "/?q=x&done=move&n=1"
    assert by_name("Bens").folder_id == fid and by_name("Mine").folder_id is None
    page = client.get(r.headers["location"]).text
    assert "1 routes moved." in page and "data-bulk-done" in page


def test_bulk_delete_only_own_routes(client, myauth, garmin):
    login(client, myauth, uid=8, username="ben")
    upload(client, "Bens", lon=13.0)
    login(client, myauth)
    upload(client, "A")
    upload(client, "B", lon=12.0)
    asyncio.run(garmin_sync.send(7, "anna", [(by_name("A").uid, "road_biking")], []))
    sha = by_name("A").gpx_sha
    page = client.get("/").text
    assert 'value="delete"' in page and "Delete {n} routes? This cannot be undone." in page
    r = bulk(client, "delete", "A", "B", "Bens", back="q=x")
    assert r.headers["location"] == "/?q=x&done=delete&n=2"
    with get_session() as s:
        assert [x.name for x in s.exec(select(Route))] == ["Bens"]       # Ben's stays
        assert len(s.exec(select(GarminCourse)).all()) == 1              # the course stays
    assert not store._path(sha).exists()                                 # file gone
    msg = client.get(r.headers["location"]).text
    assert "2 routes deleted." in msg and "Courses in Garmin Connect stay there" in msg
    assert len(garmin.accounts["tok7"]) == 1


def test_bulk_garmin_goes_on_to_send(client, myauth, garmin):
    login(client, myauth)
    upload(client, "A")
    r = bulk(client, "garmin", "A", back="q=x")
    assert r.headers["location"] == f"/garmin/send?ids={by_name('A').id}&back=%2F%3Fq%3Dx"
    assert garmin.accounts == {}                             # nothing sent yet


def test_changed_garmin_route_is_amber_in_the_list(client, myauth, garmin):
    login(client, myauth)
    upload(client, "A")
    asyncio.run(garmin_sync.send(7, "anna", [(by_name("A").uid, "road_biking")], []))
    assert '<span class="badge ok small" title="In Garmin Connect">G</span>' in client.get("/").text
    with get_session() as s:
        r = s.exec(select(Route)).one()
        r.description = "new"
        s.add(r)
        s.commit()
    page = client.get("/").text
    assert 'class="badge warn small" title="Changed since it was sent to Garmin">G</span>' in page

