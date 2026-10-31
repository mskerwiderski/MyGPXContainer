"""Who is signed in - the one interface the rest of the app uses.

`MGC_AUTH` (config.auth_mode) picks what is behind it (docs/plan-standalone.md):
- `myauth`: MyAuth signs in, enables the app per user, holds the Garmin
  connections and lists who a route can be shared with (auth/myauth.py);
- `local`: accounts of the app's own, invited by an admin, sharing between
  them; `single`: one account, no sharing (auth/local.py);
- `none`: no sign-in at all - development and tests only.

The signed-in user is `request.state.user`, a dict with at least `uid`,
`username`, `display_name`, `language`, `timezone` and `app_admin` (None
without sign-in). Pages use `gate` (the middleware), `is_admin`, `uid`,
`account`, `garmin_token`, `others` and `sharing` - never a provider itself.

A POST, PUT, PATCH or DELETE from another site is refused in every mode
(`cross_site`): apps behind one MyAuth share a host name and cookies don't
separate ports, so a form on another app's page would arrive signed in.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from ..config import get_settings
from ..i18n import N_

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


class GarminUnavailable(Exception):
    """No Garmin token for the user; `text` is an English key."""

    def __init__(self, text: str):
        super().__init__(text)
        self.text = text


class SharingUnavailable(Exception):
    """Nobody to share with can be listed; `text` is an English key."""

    def __init__(self, text: str):
        super().__init__(text)
        self.text = text


def mode() -> str:
    return get_settings().auth_mode


def _provider():
    if mode() == "myauth":
        from . import myauth
        return myauth
    if mode() in ("local", "single"):
        from . import local
        return local
    return None


def cross_site(request: Request) -> bool:
    """True for a request another site sent: its `Origin` names another host
    than the one the browser asked (or is "null"), or the browser says so in
    `Sec-Fetch-Site`. No Origin (old clients, tests) counts as same-site."""
    if request.headers.get("sec-fetch-site") == "cross-site":
        return True
    origin = request.headers.get("origin")
    if not origin:
        return False
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    return urlsplit(origin).netloc.lower() != host.split(",")[0].strip().lower()


async def gate(request: Request) -> Response | None:
    """The middleware's check: sets `request.state.user` and returns None
    when the request may go on, else the answer (sign-in, no access ...)."""
    request.state.user = None
    path = request.url.path
    if path == "/healthz" or path.startswith("/static/"):
        return None
    if request.method not in SAFE_METHODS and cross_site(request):
        return JSONResponse({"detail": "cross_site_request"}, status_code=403)
    provider = _provider()
    return await provider.gate(request) if provider else None


def user(request: Request) -> dict | None:
    return getattr(request.state, "user", None)


def is_admin(request: Request) -> bool:
    """Manages the map regions of the loop suggestions (and in mode `local`
    the people). Without sign-in (development, tests) everyone is."""
    if _provider() is None:
        return True
    return bool((user(request) or {}).get("app_admin"))


def uid(request: Request) -> int | None:
    return (user(request) or {}).get("uid")


def account(request: Request) -> dict | None:
    """Header data for the signed-in user (None without): `name`,
    `account_url`, `logout_url`, `impersonated_by`, `stop_url`."""
    provider = _provider()
    return provider.account(request, user(request)) if provider else None


def sharing() -> bool:
    """Whether routes can be shared with other people at all."""
    return mode() in ("myauth", "local")


async def garmin_token(uid: int | None) -> str:
    """The Garmin access token of user `uid` - only ever the signed-in user's."""
    provider = _provider()
    if provider is None or uid is None:
        raise GarminUnavailable(N_("Garmin is not set up for MyGPXContainer yet."))
    return await provider.garmin_token(uid)


async def others(user: dict | None) -> list[dict]:
    """[{uid, username, display_name}] of everyone the user can share with,
    without the user. Raises SharingUnavailable."""
    provider = _provider()
    if provider is None or not sharing() or not user or user.get("uid") is None:
        raise SharingUnavailable(N_("Sharing is not available here."))
    return await provider.others(user)
