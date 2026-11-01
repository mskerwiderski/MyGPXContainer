"""Modes `local` and `single`: accounts of the app's own (app/auth/local.py)."""

import re

import pytest
from sqlmodel import select

from app import routes
from app.auth import local
from app.db import get_session
from app.models import Account, AccountSession
from tests.conftest import make_gpx

PW = "correct horse battery"


@pytest.fixture
def local_mode(monkeypatch):
    monkeypatch.setenv("MGC_AUTH", "local")
    from app import config
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(local, "_fails", {})


@pytest.fixture
def single_mode(monkeypatch):
    monkeypatch.setenv("MGC_AUTH", "single")
    from app import config
    monkeypatch.setattr(config, "_settings", None)
    monkeypatch.setattr(local, "_fails", {})


def setup(client, username="anna", display_name="Anna", password=PW, code=None):
    return client.post("/setup", data={"username": username, "display_name": display_name,
                                       "password": password, "again": password,
                                       "code": local.setup_code() if code is None else code},
                       follow_redirects=False)


def accounts():
    with get_session() as s:
        return {a.username: a for a in s.exec(select(Account))}


def invite(client, username):
    page = client.post("/admin/users", data={"username": username}).text
    return re.search(r'value="https?://[^"/]+(/invite/[^"]+)"', page).group(1)


def test_password_hashes():
    stored = local.hash_password(PW)
    assert stored.startswith("scrypt$") and PW not in stored
    assert local.check_password(PW, stored) and not local.check_password("wrong one!", stored)
    assert stored != local.hash_password(PW)                 # salted
    assert not local.check_password(PW, "") and not local.check_password(PW, "md5$x")


def test_first_start_leads_to_setup_and_makes_an_admin(client, local_mode):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/setup"
    assert client.get("/login", follow_redirects=False).headers["location"] == "/setup"
    assert client.get("/healthz").status_code == 200
    wrong = setup(client, code="nope")
    assert wrong.status_code == 422 and "setup code is wrong" in wrong.text
    page = setup(client, password="short")
    assert page.status_code == 422 and "at least 10 characters" in page.text
    r = setup(client, username="Anna")
    assert r.status_code == 303 and "mgc_session" in r.headers["set-cookie"]
    assert "HttpOnly" in r.headers["set-cookie"] and "samesite=lax" in r.headers["set-cookie"].lower()
    a = accounts()["anna"]
    assert a.is_admin and a.password_hash.startswith("scrypt$")
    page = client.get("/").text
    assert "Anna" in page and 'href="/admin/users"' in page
    assert client.get("/setup", follow_redirects=False).headers["location"] == "/"
    setup(client, username="mallory")                         # setup is gone
    assert "mallory" not in accounts()


def test_sign_in_out(client, local_mode):
    setup(client)
    client.cookies.clear()
    r = client.get("/garmin", follow_redirects=False)
    assert r.headers["location"] == "/login?next=%2Fgarmin"
    assert client.post("/folders", data={"name": "X"}).status_code == 401
    bad = client.post("/login", data={"username": "anna", "password": "nope nope nope"})
    assert bad.status_code == 401 and "User name or password is wrong." in bad.text
    r = client.post("/login", data={"username": "ANNA ", "password": PW, "next": "/garmin"},
                    follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/garmin"
    page = client.get("/").text
    logout = re.search(r'href="(/logout\?t=[0-9a-f]+)"', page).group(1)
    client.get("/logout?t=0000")                              # another site's link: nothing
    assert client.get("/", follow_redirects=False).status_code == 200
    client.get(logout)
    with get_session() as s:
        assert len(s.exec(select(AccountSession)).all()) == 1   # only setup's browser left
    assert client.get("/", follow_redirects=False).status_code == 303


def test_failed_sign_ins_are_limited(client, local_mode):
    setup(client)
    client.cookies.clear()
    for _ in range(local.MAX_FAILS):
        client.post("/login", data={"username": "anna", "password": "wrong password"})
    r = client.post("/login", data={"username": "anna", "password": PW})
    assert r.status_code == 429


def test_invite_share_and_admin(client, local_mode):
    setup(client)
    link = invite(client, "ben")
    assert not accounts()["ben"].password_hash
    with get_session() as s:
        routes.create(s, make_gpx("Lake"), sport_keys=["cycling"],
                      user={"uid": accounts()["anna"].id, "username": "anna"})
    client.cookies.clear()
    assert "Set a password for “ben”" in client.get(link).text
    r = client.post(link, data={"password": PW, "again": PW}, follow_redirects=False)
    assert r.status_code == 303
    assert client.get(link).status_code == 404                # used up
    assert "Lake" not in client.get("/").text                 # Anna's route is hers
    assert client.get("/admin/users").status_code == 403
    assert 'href="/admin/users"' not in client.get("/").text
    # Ben can share with Anna, the other account
    with get_session() as s:
        ben = accounts()["ben"]
        r = routes.create(s, make_gpx("Hill", lon=12.0), sport_keys=["cycling"],
                          user={"uid": ben.id, "username": "ben"})
    page = client.get(f"/routes/share?ids={r.id}").text
    assert 'value="' + str(accounts()["anna"].id) + '"> Anna' in page
    client.post("/routes/share", data={"ids": r.id, "to": accounts()["anna"].id})
    with get_session() as s:
        assert len(routes.own(s, {"uid": accounts()["anna"].id, "username": "anna"})) == 2


def test_disabling_ends_sessions_and_reset_gives_a_new_link(client, local_mode):
    setup(client)
    link = invite(client, "ben")
    other = client.__class__(client.app, base_url=str(client.base_url))
    other.post(link, data={"password": PW, "again": PW})
    assert other.get("/", follow_redirects=False).status_code == 200
    ben = accounts()["ben"].id
    client.post(f"/admin/users/{ben}", data={"action": "disable"})
    assert other.get("/", follow_redirects=False).status_code == 303
    client.post(f"/admin/users/{ben}", data={"action": "enable"})
    page = client.post(f"/admin/users/{ben}", data={"action": "reset"}).text
    assert "/invite/" in page and not accounts()["ben"].password_hash
    me = accounts()["anna"].id
    assert "Not on your own account." in client.post(f"/admin/users/{me}",
                                                     data={"action": "disable"}).text


def test_account_language_and_password(client, local_mode):
    setup(client)
    client.post("/account", data={"display_name": "Anna M.", "language": "de",
                                  "timezone": "Europe/London"})
    page = client.get("/account").text
    assert "Konto" in page and 'value="Europe/London" selected' in page and "Anna M." in page
    bad = client.post("/account/password", data={"current": "nope", "password": PW + "2",
                                                 "again": PW + "2"})
    assert bad.status_code == 422
    client.post("/account/password", data={"current": PW, "password": PW + "2",
                                           "again": PW + "2"})
    assert local.check_password(PW + "2", accounts()["anna"].password_hash)


def test_single_mode_has_no_people_and_no_sharing(client, single_mode):
    setup(client)
    page = client.get("/").text
    assert 'href="/admin/users"' not in page and 'value="share"' not in page
    assert client.get("/admin/users").status_code == 404
    assert client.get("/routes/share?ids=1").status_code in (404, 200)


def test_cross_site_post_is_refused(client, local_mode):
    setup(client)
    r = client.post("/account", data={"display_name": "X"},
                    headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    assert accounts()["anna"].display_name == "Anna"


def test_pages_of_local_mode_are_gone_with_myauth(client, myauth):
    myauth.body = {**myauth.body}
    client.cookies.set("sso_session", "x")
    assert client.get("/login").status_code == 404
    assert client.get("/admin/users").status_code == 404


# ---------- Garmin per account (auth/garmin_link.py) ----------

class FakeSignIn:
    """garmin_login's SignIn: password "pw", MFA code "123456" if `mfa`."""
    mfa = False
    closed = 0

    def __init__(self):
        self.waiting_for_mfa = False

    def start(self, email, password):
        from app.garmin_login import signin
        if password != "pw":
            raise signin.GarminError("Garmin did not accept the e-mail or password.")
        if FakeSignIn.mfa:
            self.waiting_for_mfa = True
            return None
        return self._tokens()

    def submit_mfa(self, code):
        from app.garmin_login import signin
        if code != "123456":
            raise signin.GarminError("Garmin did not accept that code.")
        self.waiting_for_mfa = False
        return self._tokens()

    @staticmethod
    def _tokens():
        import time
        return {"oauth1": {"oauth_token": "o1", "oauth_token_secret": "s1"},
                "oauth2": {"access_token": "tok-first", "expires_at": time.time() + 3600},
                "account": "Anna Garmin"}

    def close(self):
        FakeSignIn.closed += 1


@pytest.fixture
def fake_signin(monkeypatch, tmp_path):
    from app.auth import garmin_link
    FakeSignIn.mfa, FakeSignIn.closed = False, 0
    monkeypatch.setattr(garmin_link, "_signin", FakeSignIn)
    renewed = []

    def renew(oauth1):
        import time
        renewed.append(oauth1)
        return {"access_token": "tok-renewed", "expires_at": time.time() + 3600}
    monkeypatch.setattr(garmin_link, "_renew", renew)
    return renewed


def test_connect_garmin_with_mfa_and_use_it(client, local_mode, fake_signin, garmin):
    import asyncio

    from app import auth, config
    from app.auth import garmin_link
    from app.models import GarminLink
    setup(client)
    uid = accounts()["anna"].id
    with pytest.raises(auth.GarminUnavailable, match="Connect it under Account"):
        asyncio.run(auth.garmin_token(uid))
    page = client.get("/account").text
    assert "Connect Garmin" in page and "stored nowhere" in page
    bad = client.post("/account/garmin", data={"email": "a@example.org", "password": "nope"})
    assert bad.status_code == 422 and "did not accept" in bad.text
    FakeSignIn.mfa = True
    page = client.post("/account/garmin", data={"email": "a@example.org", "password": "pw"}).text
    assert 'name="code"' in page
    wrong = client.post("/account/garmin/code", data={"code": "000000"})
    assert wrong.status_code == 422 and 'name="code"' in wrong.text     # may try again
    client.post("/account/garmin/code", data={"code": "123456"})
    page = client.get("/account").text
    assert "Anna Garmin" in page and "Disconnect" in page
    with get_session() as s:
        row = s.exec(select(GarminLink)).one()
    # encrypted: none of the plain JSON (short values like "o1" may turn up
    # in random ciphertext by chance - the field names do not)
    assert "access_token" not in row.oauth2 and "oauth_token_secret" not in row.oauth1
    key = config.get_settings().data_dir / "secret.key"
    assert key.exists() and oct(key.stat().st_mode & 0o777) == "0o600"
    assert asyncio.run(auth.garmin_token(uid)) == "tok-first"
    # due: renewed with the OAuth1 token, and kept
    with get_session() as s:
        row = s.exec(select(GarminLink)).one()
        row.oauth2 = garmin_link._seal({"access_token": "old", "expires_at": 0})
        s.add(row)
        s.commit()
    assert asyncio.run(auth.garmin_token(uid)) == "tok-renewed"
    assert fake_signin == [{"oauth_token": "o1", "oauth_token_secret": "s1"}]
    assert asyncio.run(auth.garmin_token(uid)) == "tok-renewed" and len(fake_signin) == 1
    # the rest of the app uses it: sending a route
    with get_session() as s:
        r = routes.create(s, make_gpx("Lake"), sport_keys=["gravel_cycling"],
                          user={"uid": uid, "username": "anna"})
    from app import garmin_sync
    asyncio.run(garmin_sync.send(uid, "anna", [(r.uid, "gravel_cycling")], []))
    assert len(garmin.accounts["tok-renewed"]) == 1
    client.post("/account/garmin/remove")
    with get_session() as s:
        assert s.exec(select(GarminLink)).all() == []


def test_a_garmin_link_is_per_account(client, local_mode, fake_signin):
    import asyncio

    from app import auth
    setup(client)
    client.post("/account/garmin", data={"email": "a@example.org", "password": "pw"})
    link = invite(client, "ben")
    other = client.__class__(client.app, base_url=str(client.base_url))
    other.post(link, data={"password": PW, "again": PW})
    assert "Connect Garmin" in other.get("/account").text
    with pytest.raises(auth.GarminUnavailable):
        asyncio.run(auth.garmin_token(accounts()["ben"].id))


def test_the_setup_code_comes_from_the_log_or_the_setting(client, local_mode, monkeypatch,
                                                         caplog):
    import logging

    from app import config
    with caplog.at_level(logging.WARNING):
        local.announce_setup()
    code = local.setup_code()
    assert len(code) == 8 and code in caplog.text
    assert oct((config.get_settings().data_dir / "setup-code").stat().st_mode & 0o777) == "0o600"
    setup(client)
    assert not (config.get_settings().data_dir / "setup-code").exists()     # used up
    monkeypatch.setenv("MGC_SETUP_CODE", "from-the-env")
    monkeypatch.setattr(config, "_settings", None)
    assert local.setup_code() == "from-the-env"


def test_parallel_setups_make_one_admin(client, local_mode):
    from concurrent.futures import ThreadPoolExecutor
    code = local.setup_code()
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda i: setup(client.__class__(client.app, base_url=str(client.base_url)),
                                      username=f"admin{i}", code=code), range(4)))
    assert len(accounts()) == 1


def test_sign_ins_are_limited_per_user_name_too(client, local_mode, monkeypatch):
    setup(client)
    client.cookies.clear()
    hosts = iter(f"10.0.0.{i}" for i in range(1, 50))
    monkeypatch.setattr(local, "_attempt_keys",
                        lambda request, username: ["ip:" + next(hosts), "user:" + username])
    for _ in range(local.MAX_FAILS):
        client.post("/login", data={"username": "anna", "password": "wrong password"})
    r = client.post("/login", data={"username": "anna", "password": PW})
    assert r.status_code == 429                   # new address, same user name


def test_a_too_large_body_is_refused(client):
    r = client.post("/routes", content=b"x", headers={"content-length": str(200 * 1024 * 1024),
                                                      "content-type": "multipart/form-data"})
    assert r.status_code == 413
