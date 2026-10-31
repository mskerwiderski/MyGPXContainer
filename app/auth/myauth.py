"""Mode `myauth`: sign-in, Garmin and the people to share with come from
MyAuth (the author's own sign-in service), through the MyCommons building
block `access` (app/access/ is a copy - never edit it here; change it in
MyCommons, run its tests and sync it into every user).

Every request (except /healthz and /static) is checked live against MyAuth:
`access.web.check` sends the browser's `sso_session` cookie to
`GET {MGC_AUTH_URL}/api/session?app=mygpxcontainer` (cached 30 s), so
disabling a user or revoking the app takes effect within that time. The
public MyAuth pages are on the same host as this app (private name or LAN
IP), port MGC_AUTH_PUBLIC_PORT - cookies don't separate ports, so the login
there is valid here. MyAuth unreachable -> 503 (fail closed).

What stays here: the pages for each outcome (English/German through i18n),
the user's Garmin token (always the signed-in user's, never someone else's)
and who a route can be shared with: the active users with MyGPXContainer
(`GET /api/internal/members`, app flag `"members": true`), asked with the
signed-in user's uid, never kept beyond MEMBERS_TTL_S. `app_admin` from
MyAuth manages the map regions. The tests' mock points are
`access.myauth._fetch_session(cookie)`, `_fetch_garmin(uid)` and
`auth.myauth._fetch_members(uid)`.
"""

from __future__ import annotations

import time

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from .. import web
from ..access import myauth
from ..access import web as access_web
from ..config import get_settings
from ..i18n import N_
from . import GarminUnavailable, SharingUnavailable

APP_KEY = "mygpxcontainer"
MEMBERS_TTL_S = 60

# MyAuth's address and public port come from this app's own settings
# (MGC_AUTH_URL, MGC_AUTH_PUBLIC_PORT); the app key for Garmin tokens and the
# member list is MYAUTH_APP_KEY, the name the block reads as well.
myauth.configure(app=APP_KEY, platform="Garmin",
                 auth_url=lambda: get_settings().auth_url,
                 public_port=lambda: get_settings().auth_public_port)

_members: dict[int, tuple[float, list[dict]]] = {}


def login_required(request: Request, password_change: bool = False) -> Response:
    if request.method in ("GET", "HEAD"):
        return RedirectResponse(access_web.login_target(request, password_change),
                                status_code=303)
    return JSONResponse({"detail": "not_authenticated"}, status_code=401)


def _page(request: Request, status_code: int, title: str, text: str) -> Response:
    if request.method not in ("GET", "HEAD"):
        return JSONResponse({"detail": title}, status_code=status_code)
    return web.render(request, "auth_error.html", status_code, title=title, text=text,
                      account_url=access_web.myauth_page(request),
                      logout_url=access_web.myauth_page(request, "/logout?next=/login"))


def forbidden(request: Request) -> Response:
    return _page(request, 403, N_("No access"),
                 N_("Your account is not enabled for MyGPXContainer. "
                    "An administrator can change that in MyAuth."))


def unavailable(request: Request) -> Response:
    return _page(request, 503, N_("Sign-in unavailable"),
                 N_("The sign-in service MyAuth is not responding right now. "
                    "Please try again in a moment."))


async def gate(request: Request) -> Response | None:
    found = await access_web.check(request)
    if found.outcome == access_web.OK:
        request.state.user = found.user
        return None
    if found.outcome == access_web.NO_ACCESS:
        return forbidden(request)
    if found.outcome == access_web.SIGN_IN:
        return login_required(request)
    if found.outcome == access_web.CHANGE_PASSWORD:
        return login_required(request, password_change=True)
    return unavailable(request)


def account(request: Request, user: dict | None) -> dict | None:
    return access_web.account(request, user)


async def garmin_token(uid: int) -> str:
    """Garmin access token of user `uid` (MyAuth renews it itself)."""
    if not get_settings().myauth_app_key:
        raise GarminUnavailable(N_("Garmin is not set up for MyGPXContainer yet."))
    try:
        token = await myauth.garmin_token(uid)
    except myauth.GarminRefused as exc:
        raise GarminUnavailable(N_("Garmin refused the sign-in. Please try again later.")) from exc
    except myauth.Unavailable as exc:
        raise GarminUnavailable(N_("MyAuth is not reachable right now.")) from exc
    if token is None:
        raise GarminUnavailable(N_("Your Garmin account is not connected. "
                                   "Connect it under Connections in MyAuth."))
    return token["access_token"]


async def _fetch_members(uid: int) -> tuple[int, dict]:
    return await myauth.call("GET", "/api/internal/members", uid=uid)


async def others(user: dict) -> list[dict]:
    if not get_settings().myauth_app_key:
        raise SharingUnavailable(N_("Sharing needs MyAuth, which is not set up here."))
    uid = user["uid"]
    hit = _members.get(uid)
    if hit and hit[0] > time.monotonic():
        members = hit[1]
    else:
        try:
            status, body = await _fetch_members(uid)
        except myauth.Unavailable as exc:
            raise SharingUnavailable(N_("MyAuth is not reachable right now.")) from exc
        if status != 200 or not isinstance(body.get("members"), list):
            raise SharingUnavailable(N_("MyAuth does not list the users of MyGPXContainer."))
        members = [{"uid": int(m["uid"]), "username": str(m["username"]),
                    "display_name": str(m.get("display_name") or m["username"])}
                   for m in body["members"] if m.get("uid") is not None and m.get("username")]
        _members[uid] = (time.monotonic() + MEMBERS_TTL_S, members)
    return [m for m in members if (m["uid"], m["username"]) != (uid, user.get("username"))]


def clear_cache() -> None:
    _members.clear()
