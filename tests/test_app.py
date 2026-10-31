
from app.version import __version__
from tests.conftest import USER


def test_healthz_reports_version(client):
    assert client.get("/healthz").json() == {"status": "ok", "version": __version__}


def test_routes_page_without_login(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "No routes yet" in r.text


def test_static_assets_have_cache_buster(client):
    r = client.get("/")
    assert "/static/ui/tokens.css?v=" in r.text and "/static/app.css?v=" in r.text


def test_no_cookie_redirects_to_myauth_login(client, myauth):
    r = client.get("/?x=1", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == (
        "https://phoenix.example:1000/login?next=https%3A%2F%2Fphoenix.example%3A1016%2F%3Fx%3D1")


def test_healthz_needs_no_login(client, myauth):
    assert client.get("/healthz").status_code == 200


def test_signed_in_user_in_header(client, myauth):
    client.cookies.set("sso_session", "abc")
    r = client.get("/")
    assert r.status_code == 200
    assert "Anna Muster" in r.text and "https://phoenix.example:1000/logout" in r.text


def test_session_is_cached(client, myauth):
    client.cookies.set("sso_session", "abc")
    client.get("/")
    client.get("/")
    assert myauth.calls == 1


def test_app_not_granted_is_403(client, myauth):
    myauth.status, myauth.body = 403, {"detail": "app_not_allowed"}
    client.cookies.set("sso_session", "abc")
    r = client.get("/")
    assert r.status_code == 403 and "No access" in r.text


def test_password_change_required(client, myauth):
    myauth.status, myauth.body = 401, {"detail": "password_change_required"}
    client.cookies.set("sso_session", "abc")
    r = client.get("/", follow_redirects=False)
    assert r.headers["location"].startswith("https://phoenix.example:1000/password?next=")


def test_myauth_down_fails_closed(client, myauth, monkeypatch):
    from app.access import myauth

    async def down(cookie):
        raise myauth.Unavailable("down")
    monkeypatch.setattr(myauth, "_fetch_session", down)
    client.cookies.set("sso_session", "abc")
    r = client.get("/")
    assert r.status_code == 503 and "Sign-in unavailable" in r.text


def test_impersonation_banner(client, myauth):
    myauth.body = {**myauth.body, "impersonated_by": {"username": "admin", "display_name": "Max"}}
    client.cookies.set("sso_session", "abc")
    r = client.get("/")
    assert "on behalf of Max" in r.text and "/impersonate/stop?next=" in r.text


# ---------- cross-site requests (auth.cross_site) ----------

def test_a_post_from_another_site_is_refused(client, myauth):
    myauth.body = dict(USER)
    client.cookies.set("sso_session", "x")
    host = "phoenix.example:1016"
    evil = {"origin": "https://phoenix.example:1015"}     # another app, same host name
    assert client.post("/folders", data={"name": "X"}, headers=evil).status_code == 403
    assert client.post("/folders", data={"name": "X"},
                       headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert client.post("/folders", data={"name": "X"},
                       headers={"origin": "null"}).status_code == 403
    ok = client.post("/folders", data={"name": "Mine"}, headers={"origin": f"https://{host}"},
                     follow_redirects=False)
    assert ok.status_code == 303
    behind_proxy = {"origin": "https://maps.example", "x-forwarded-host": "maps.example"}
    assert client.post("/folders", data={"name": "Other"}, headers=behind_proxy,
                       follow_redirects=False).status_code == 303
    assert client.get("/", headers=evil).status_code == 200    # reading is fine


def test_cross_site_is_refused_without_sign_in_too(client):
    r = client.post("/folders", data={"name": "X"}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403


def test_a_route_name_cannot_end_a_script_block(client):
    """Security review 2026-10-31: the map view printed route names into a
    <script type="application/json"> block unescaped."""
    from xml.sax.saxutils import escape

    from app import routes
    from app.db import get_session
    from tests.conftest import make_gpx
    evil = "</script><script>alert(1)</script>"
    with get_session() as s:
        r = routes.create(s, make_gpx(escape(evil)))      # the file has it XML-escaped
    assert r.name == evil
    for page in (client.get("/?view=map").text, client.get(f"/routes/{r.id}").text):
        assert "<script>alert(1)" not in page
    assert "\\u003c/script\\u003e\\u003cscript\\u003ealert(1)" in client.get("/?view=map").text


def test_back_links_stay_on_this_app():
    from app.web import local_path
    for ok in ("/", "/routes/1?x=2", "/?q=a%2Fb"):
        assert local_path(ok)
    for bad in ("//evil.example", "/\\evil.example", "https://evil.example", "evil", "/x\ny", ""):
        assert not local_path(bad)
