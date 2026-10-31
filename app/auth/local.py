"""Modes `local` and `single`: accounts of the app's own (v0.19.0,
docs/plan-standalone.md).

- The first start has no account: every page leads to /setup, which makes
  the first one - an admin - with the setup code: MGC_SETUP_CODE, else a
  random one in the data dir's `setup-code`, written to the log at start
  (whoever reaches a fresh instance first must not become its admin). One
  setup at a time (`_setup_lock`); after it /setup is gone.
- `local`: the admin invites people on /admin/users - a one-time link
  (INVITE_DAYS) where they set their password; no open sign-up. The admin
  can disable an account, make it admin or reset its password (a new link).
  Sharing goes between the active accounts.
- `single`: one person - no invitations, no sharing.

Passwords: scrypt from the standard library (`hash_password`). A sign-in
gives a random token in the `mgc_session` cookie (HttpOnly, SameSite=Lax,
Secure behind https); the table keeps only its sha256 (SESSION_DAYS).
Sign-ins are limited per address AND per user name (MAX_FAILS failures in
FAIL_WINDOW_S), counted before the password is checked; behind a reverse
proxy the address is the client's only with uvicorn's FORWARDED_ALLOW_IPS.
An unknown user name costs the same scrypt as a known one. The log-out
link carries a value derived from the session, so another site cannot sign
the user out. Garmin per account: auth/garmin_link.py (v0.20.0), connected
on the account page.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import os
import secrets
import threading
import time
from datetime import UTC, timedelta
from urllib.parse import quote
from zoneinfo import available_timezones

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlmodel import Session, func, select

from .. import i18n, web
from ..config import get_settings
from ..db import get_session
from ..garmin_login import signin
from ..i18n import N_
from ..models import Account, AccountSession, now_utc
from . import SharingUnavailable, garmin_link, mode

COOKIE = "mgc_session"
SESSION_DAYS = 30
INVITE_DAYS = 7
MAX_FAILS, FAIL_WINDOW_S = 5, 900
MIN_PASSWORD = 10
PUBLIC = ("/login", "/setup", "/invite/", "/healthz", "/static/")

router = APIRouter()
log = logging.getLogger(__name__)
_fails: dict[str, list[float]] = {}
_setup_lock = threading.Lock()
_DUMMY_HASH = ""


# ---------- passwords, tokens ----------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$16384$8$1$" + base64.b64encode(salt).decode() + "$" + \
        base64.b64encode(digest).decode()


def check_password(password: str, stored: str) -> bool:
    try:
        kind, n, r, p, salt, digest = stored.split("$")
        if kind != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n),
                             r=int(r), p=int(p), dklen=32)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, base64.b64decode(digest))


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _password_problem(password: str, again: str) -> str:
    if len(password) < MIN_PASSWORD:
        return N_("The password needs at least 10 characters.")
    if password != again:
        return N_("The two passwords differ.")
    return ""


def _clean_username(name: str) -> str:
    return name.strip().lower()


def _username_problem(session: Session, name: str) -> str:
    if not name or len(name) > 40 or not all(c.isalnum() or c in "._-" for c in name):
        return N_("A user name has letters, digits, dot, dash or underscore (at most 40).")
    if session.exec(select(Account).where(Account.username == name)).first():
        return N_("This user name is taken.")
    return ""


# ---------- the signed-in account ----------

def _count(session: Session) -> int:
    return session.exec(select(func.count()).select_from(Account)).one()


def _user_record(account: Account, request: Request) -> dict:
    """The same shape MyAuth answers with (auth.__init__)."""
    return {"uid": account.id, "username": account.username,
            "display_name": account.display_name or account.username,
            "language": account.language
            or i18n.pick(None, request.headers.get("accept-language", "")),
            "timezone": account.timezone or None, "app_admin": account.is_admin,
            "impersonated_by": None}


def _signed_in(request: Request) -> Account | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    with get_session() as s:
        row = s.exec(select(AccountSession).where(
            AccountSession.token_hash == _sha(token))).first()
        if not row or _aware(row.expires_at) < now_utc():
            return None
        account = s.get(Account, row.account_id)
        return account if account and account.active and account.password_hash else None


def _aware(value):
    """SQLite gives back naive datetimes; they were stored as UTC."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _public(path: str) -> bool:
    return any(path == p.rstrip("/") or path.startswith(p) for p in PUBLIC)


async def gate(request: Request) -> Response | None:
    path = request.url.path
    with get_session() as s:
        empty = _count(s) == 0
    if empty:            # the first start: only /setup (and what it needs)
        if path in ("/setup", "/healthz") or path.startswith("/static/"):
            return None
        return _to(request, "/setup")
    account = _signed_in(request)
    if account:
        request.state.user = _user_record(account, request)
        return None
    if _public(path):
        return None
    if request.method in ("GET", "HEAD"):
        here = path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse("/login?next=" + quote(here, safe=""), status_code=303)
    return JSONResponse({"detail": "not_authenticated"}, status_code=401)


def _to(request: Request, path: str) -> Response:
    if request.method in ("GET", "HEAD"):
        return RedirectResponse(path, status_code=303)
    return JSONResponse({"detail": "setup_needed"}, status_code=409)


def account(request: Request, user: dict | None) -> dict | None:
    if not user:
        return None
    token = request.cookies.get(COOKIE, "")
    return {"name": user["display_name"], "account_url": "/account",
            "logout_url": "/logout?t=" + _sha("logout" + token)[:20],
            "impersonated_by": None, "stop_url": None}


async def garmin_token(uid: int) -> str:
    return await asyncio.to_thread(garmin_link.token, uid)


async def others(user: dict) -> list[dict]:
    if mode() != "local":
        raise SharingUnavailable(N_("Sharing is not available here."))
    with get_session() as s:
        rows = s.exec(select(Account).where(Account.active == True,  # noqa: E712 - SQL
                                            Account.password_hash != "",
                                            Account.id != user["uid"])).all()
    people = [{"uid": a.id, "username": a.username,
               "display_name": a.display_name or a.username} for a in rows]
    return sorted(people, key=lambda m: m["display_name"].casefold())


# ---------- signing in and out ----------

def _start_session(request: Request, account_id: int, target: str) -> Response:
    token = secrets.token_urlsafe(32)
    with get_session() as s:
        s.add(AccountSession(token_hash=_sha(token), account_id=account_id,
                             expires_at=now_utc() + timedelta(days=SESSION_DAYS)))
        s.commit()
    r = RedirectResponse(_local(target), status_code=303)
    https = request.url.scheme == "https" or \
        request.headers.get("x-forwarded-proto", "").startswith("https")
    r.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True,
                 samesite="lax", secure=https, path="/")
    return r


def _local(path: str) -> str:
    return path if web.local_path(path) else "/"


def _attempt_keys(request: Request, username: str) -> list[str]:
    return ["ip:" + (request.client.host if request.client else "?"),
            "user:" + _clean_username(username)]


def _too_many(keys: list[str]) -> bool:
    """Counts this attempt, and says whether there were too many before it."""
    now = time.monotonic()
    if len(_fails) > 10000:                    # forget the stale ones
        for k in [k for k, v in _fails.items() if not v or v[-1] < now - FAIL_WINDOW_S]:
            del _fails[k]
    blocked = False
    for key in keys:
        recent = [t for t in _fails.get(key, []) if t > now - FAIL_WINDOW_S]
        blocked = blocked or len(recent) >= MAX_FAILS
        _fails[key] = [*recent, now]
    return blocked


def _succeeded(keys: list[str]) -> None:
    for key in keys:
        if _fails.get(key):
            _fails[key].pop()


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if not _DUMMY_HASH:
        _DUMMY_HASH = hash_password(secrets.token_hex(8))
    return _DUMMY_HASH


def _own_mode(request: Request) -> Response | None:
    """These pages only exist in modes local and single."""
    if mode() in ("local", "single"):
        return None
    return web.error(request, 404, N_("Page not found"))


@router.get("/login")
def login_page(request: Request):
    if (no := _own_mode(request)) is not None:
        return no
    return web.render(request, "login.html", next=_local(request.query_params.get("next", "/")))


@router.post("/login")
def login(request: Request, username: str = Form(""), password: str = Form(""),
          next: str = Form("/")):
    if (no := _own_mode(request)) is not None:
        return no
    keys = _attempt_keys(request, username)
    if _too_many(keys):
        return web.render(request, "login.html", 429, next=next, username=username,
                          problem=N_("Too many failed attempts. Please wait a few minutes."))
    with get_session() as s:
        found = s.exec(select(Account).where(
            Account.username == _clean_username(username))).first()
        stored = found.password_hash if found and found.active and found.password_hash else ""
        ok = check_password(password, stored or _dummy_hash()) and bool(stored)
    if ok:
        _succeeded(keys)
    else:
        return web.render(request, "login.html", 401, next=next, username=username,
                          problem=N_("User name or password is wrong."))
    return _start_session(request, found.id, next)


@router.get("/logout")
def logout(request: Request, t: str = ""):
    token = request.cookies.get(COOKIE, "")
    if not (token and hmac.compare_digest(t, _sha("logout" + token)[:20])):
        return RedirectResponse("/", status_code=303)       # not our own link
    with get_session() as s:
        row = s.exec(select(AccountSession).where(
            AccountSession.token_hash == _sha(token))).first()
        if row:
            s.delete(row)
            s.commit()
    r = RedirectResponse("/login", status_code=303)
    r.delete_cookie(COOKIE, path="/")
    return r


# ---------- the first account ----------

def setup_code() -> str:
    """MGC_SETUP_CODE, else the one in the data dir (made when missing)."""
    s = get_settings()
    if s.setup_code:
        return s.setup_code
    path = s.data_dir / "setup-code"
    if not path.exists():
        s.ensure_dirs()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(4))
    return path.read_text().strip()


def announce_setup() -> None:
    """At start, before the first account exists: the code goes to the log."""
    if mode() not in ("local", "single"):
        return
    with get_session() as s:
        if _count(s):
            return
    log.warning("No account yet: open /setup in the browser and enter the setup code %s",
                setup_code())

@router.get("/setup")
def setup_page(request: Request):
    if (no := _own_mode(request)) is not None:
        return no
    with get_session() as s:
        if _count(s):
            return RedirectResponse("/", status_code=303)
    return web.render(request, "setup.html")


@router.post("/setup")
def setup(request: Request, username: str = Form(""), display_name: str = Form(""),
          password: str = Form(""), again: str = Form(""), code: str = Form("")):
    if (no := _own_mode(request)) is not None:
        return no
    name = _clean_username(username)
    if _too_many(["setup"]):
        return web.render(request, "setup.html", 429, username=username,
                          display_name=display_name,
                          problem=N_("Too many failed attempts. Please wait a few minutes."))
    with _setup_lock, get_session() as s:     # one at a time: never two first admins
        if _count(s):
            return RedirectResponse("/", status_code=303)
        problem = (N_("The setup code is wrong. It is in the app's log.")
                   if not hmac.compare_digest(code.strip().encode(), setup_code().encode())
                   else _username_problem(s, name) or _password_problem(password, again))
        if problem:
            return web.render(request, "setup.html", 422, problem=problem, username=username,
                              display_name=display_name)
        _succeeded(["setup"])
        a = Account(username=name, display_name=display_name.strip()[:80],
                    password_hash=hash_password(password), is_admin=True)
        s.add(a)
        s.commit()
        s.refresh(a)
    (get_settings().data_dir / "setup-code").unlink(missing_ok=True)
    return _start_session(request, a.id, "/")


# ---------- the user's own account ----------

def _zones() -> list[str]:
    return sorted(z for z in available_timezones() if "/" in z and not z.startswith("Etc/"))


def _account_page(request: Request, status_code: int = 200, **extra):
    with get_session() as s:
        a = s.get(Account, request.state.user["uid"])
    return web.render(request, "account.html", status_code, me=a, zones=_zones(),
                      langs=i18n.LANGS, garmin=garmin_link.link_of(a.id),
                      garmin_code=garmin_link.waiting_for_code(a.id), **extra)


@router.get("/account")
def account_page(request: Request):
    if (no := _own_mode(request)) is not None:
        return no
    return _account_page(request)


@router.post("/account")
def account_save(request: Request, display_name: str = Form(""), language: str = Form(""),
                 timezone: str = Form("")):
    if (no := _own_mode(request)) is not None:
        return no
    if language not in ("", *i18n.LANGS) or (timezone and timezone not in available_timezones()):
        return _account_page(request, 422, problem=N_("Unknown language or time zone."))
    with get_session() as s:
        a = s.get(Account, request.state.user["uid"])
        a.display_name, a.language, a.timezone = display_name.strip()[:80], language, timezone
        s.add(a)
        s.commit()
    return RedirectResponse("/account?saved=1", status_code=303)


@router.post("/account/password")
def account_password(request: Request, current: str = Form(""), password: str = Form(""),
                     again: str = Form("")):
    if (no := _own_mode(request)) is not None:
        return no
    with get_session() as s:
        a = s.get(Account, request.state.user["uid"])
        problem = (N_("The current password is wrong.")
                   if not check_password(current, a.password_hash)
                   else _password_problem(password, again))
        if problem:
            return _account_page(request, 422, password_problem=problem)
        a.password_hash = hash_password(password)
        s.add(a)
        token = _sha(request.cookies.get(COOKIE, ""))
        for other in s.exec(select(AccountSession).where(       # other browsers sign in again
                AccountSession.account_id == a.id, AccountSession.token_hash != token)):
            s.delete(other)
        s.commit()
    return RedirectResponse("/account?password=1", status_code=303)


# ---------- Garmin Connect of the account ----------

@router.post("/account/garmin")
def garmin_connect(request: Request, email: str = Form(""), password: str = Form("")):
    """Blocking sign-in at Garmin (a sync endpoint: it runs in the thread pool)."""
    if (no := _own_mode(request)) is not None:
        return no
    try:
        done = garmin_link.connect(request.state.user["uid"], email, password)
    except signin.GarminError as e:
        return _account_page(request, 422, garmin_problem=str(e), garmin_email=email)
    if not done:
        return _account_page(request)          # asks for the code now
    return RedirectResponse("/account?garmin=1#garmin", status_code=303)


@router.post("/account/garmin/code")
def garmin_code(request: Request, code: str = Form("")):
    if (no := _own_mode(request)) is not None:
        return no
    try:
        garmin_link.submit_code(request.state.user["uid"], code)
    except signin.GarminError as e:
        return _account_page(request, 422, garmin_problem=str(e))
    return RedirectResponse("/account?garmin=1#garmin", status_code=303)


@router.post("/account/garmin/remove")
def garmin_remove(request: Request):
    """Forgets the tokens (also an open sign-in). The courses in Garmin stay."""
    if (no := _own_mode(request)) is not None:
        return no
    garmin_link.disconnect(request.state.user["uid"])
    return RedirectResponse("/account#garmin", status_code=303)


# ---------- people (mode local, admins) ----------

def _admin_only(request: Request) -> Response | None:
    if mode() != "local":
        return web.error(request, 404, N_("Page not found"))
    if not (request.state.user or {}).get("app_admin"):
        return web.error(request, 403, N_("Not allowed"), N_("Only admins manage the people."))
    return None


def _invite(a: Account) -> str:
    token = secrets.token_urlsafe(24)
    a.invite_hash = _sha(token)
    a.invite_expires = now_utc() + timedelta(days=INVITE_DAYS)
    return token


def _users_page(request: Request, status_code: int = 200, **extra):
    with get_session() as s:
        people = s.exec(select(Account).order_by(Account.username)).all()
    base = str(request.base_url).rstrip("/")
    proto = request.headers.get("x-forwarded-proto")
    host = request.headers.get("x-forwarded-host")
    if proto and host:
        base = f"{proto}://{host}"
    return web.render(request, "admin_users.html", status_code, people=people,
                      base=base, account_uid=request.state.user["uid"], **extra)


@router.get("/admin/users")
def users_page(request: Request):
    if (no := _admin_only(request)) is not None:
        return no
    return _users_page(request)


@router.post("/admin/users")
def user_invite(request: Request, username: str = Form(""), display_name: str = Form("")):
    if (no := _admin_only(request)) is not None:
        return no
    name = _clean_username(username)
    with get_session() as s:
        problem = _username_problem(s, name)
        if problem:
            return _users_page(request, 422, problem=problem, username=username,
                               display_name=display_name)
        a = Account(username=name, display_name=display_name.strip()[:80])
        token = _invite(a)
        s.add(a)
        s.commit()
    return _users_page(request, link=("/invite/" + token, name))


@router.post("/admin/users/{account_id}")
def user_change(request: Request, account_id: int, action: str = Form("")):
    """reset (a new invitation link, the password goes), disable, enable,
    admin, no_admin - never on the admin's own account."""
    if (no := _admin_only(request)) is not None:
        return no
    if account_id == request.state.user["uid"]:
        return _users_page(request, 422, problem=N_("Not on your own account."))
    link = None
    with get_session() as s:
        a = s.get(Account, account_id)
        if not a:
            return web.error(request, 404, N_("Page not found"))
        if action == "reset":
            a.password_hash = ""
            link = ("/invite/" + _invite(a), a.username)
        elif action in ("disable", "enable"):
            a.active = action == "enable"
        elif action in ("admin", "no_admin"):
            a.is_admin = action == "admin"
        else:
            return web.error(request, 422, N_("Unknown action"))
        if action in ("reset", "disable"):
            for row in s.exec(select(AccountSession).where(AccountSession.account_id == a.id)):
                s.delete(row)
        s.add(a)
        s.commit()
    return _users_page(request, link=link)


# ---------- invitations ----------

def _invited(token: str) -> Account | None:
    with get_session() as s:
        a = s.exec(select(Account).where(Account.invite_hash == _sha(token))).first()
    if not a or not a.active or not a.invite_expires or _aware(a.invite_expires) < now_utc():
        return None
    return a


@router.get("/invite/{token}")
def invite_page(request: Request, token: str):
    if (no := _own_mode(request)) is not None:
        return no
    a = _invited(token)
    if not a:
        return web.error(request, 404, N_("This link is not valid (any more)."),
                         N_("Ask whoever invited you for a new one."))
    return web.render(request, "invite.html", invited=a, token=token)


@router.post("/invite/{token}")
def invite_accept(request: Request, token: str, password: str = Form(""),
                  again: str = Form("")):
    if (no := _own_mode(request)) is not None:
        return no
    a = _invited(token)
    if not a:
        return web.error(request, 404, N_("This link is not valid (any more)."),
                         N_("Ask whoever invited you for a new one."))
    problem = _password_problem(password, again)
    if problem:
        return web.render(request, "invite.html", 422, invited=a, token=token, problem=problem)
    with get_session() as s:
        a = s.get(Account, a.id)
        a.password_hash, a.invite_hash, a.invite_expires = hash_password(password), "", None
        s.add(a)
        s.commit()
    return _start_session(request, a.id, "/")
