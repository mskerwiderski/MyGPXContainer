"""Garmin Connect for own accounts (modes local and single, v0.20.0).

The sign-in itself is the MyCommons block `garmin_login` (app/garmin_login/
is a copy - never edit it here; `MyCommons/sync.sh garmin_login app`), like
the Garmin MCP's standalone mode. What stays here:
- a sign-in waiting for its MFA code, per uid, across two requests
  (`_pending`, at most PENDING_S);
- the tokens per uid in `GarminLink`, encrypted with Fernet. The key is
  MGC_SECRET_KEY, else `secret.key` in the data dir, made on first use
  (readable by the app only). Losing the key means connecting Garmin again;
- renewing the access token when it is due (`token`), one at a time per uid.
The password goes to Garmin once and is stored nowhere. Mock points of the
tests: `_signin()` (a SignIn) and `_renew(oauth1)`.
"""

from __future__ import annotations

import json
import os
import threading
import time

from cryptography.fernet import Fernet, InvalidToken
from sqlmodel import select

from ..config import get_settings
from ..db import get_session
from ..garmin_login import signin
from ..i18n import N_
from ..models import GarminLink, now_utc
from . import GarminUnavailable

PENDING_S = 300

_pending: dict[int, tuple[float, signin.SignIn]] = {}
_locks: dict[int, threading.Lock] = {}
_fernet: Fernet | None = None


def _key() -> Fernet:
    global _fernet
    if _fernet is None:
        s = get_settings()
        key = os.environ.get("MGC_SECRET_KEY", "").encode()
        if not key:
            path = s.data_dir / "secret.key"
            if not path.exists():
                s.ensure_dirs()
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(Fernet.generate_key())
            key = path.read_bytes().strip()
        _fernet = Fernet(key)
    return _fernet


def _seal(value: dict) -> str:
    return _key().encrypt(json.dumps(value).encode()).decode()


def _open(value: str) -> dict:
    return json.loads(_key().decrypt(value.encode()))


def _signin() -> signin.SignIn:
    return signin.SignIn()


def _renew(oauth1: dict) -> dict:
    return signin.renew(oauth1)


def link_of(uid: int) -> GarminLink | None:
    with get_session() as s:
        return s.exec(select(GarminLink).where(GarminLink.uid == uid)).first()


def _save(uid: int, tokens: dict) -> None:
    with get_session() as s:
        row = s.exec(select(GarminLink).where(GarminLink.uid == uid)).first() or GarminLink(uid=uid)
        row.garmin_name = tokens.get("account") or ""
        row.oauth1, row.oauth2 = _seal(tokens["oauth1"]), _seal(tokens["oauth2"])
        row.connected_at, row.error = now_utc(), ""
        s.add(row)
        s.commit()


def _drop_pending(uid: int) -> None:
    hit = _pending.pop(uid, None)
    if hit:
        hit[1].close()


def waiting_for_code(uid: int) -> bool:
    hit = _pending.get(uid)
    if hit and hit[0] < time.monotonic() - PENDING_S:
        _drop_pending(uid)
        return False
    return hit is not None


def connect(uid: int, email: str, password: str) -> bool:
    """Signs in to Garmin. True: connected; False: Garmin wants the MFA code
    (`submit_code`). Raises signin.GarminError with a text for the user."""
    _drop_pending(uid)
    attempt = _signin()
    try:
        tokens = attempt.start(email, password)
    except Exception:
        attempt.close()
        raise
    if tokens is None:
        _pending[uid] = (time.monotonic(), attempt)
        return False
    attempt.close()
    _save(uid, tokens)
    return True


def submit_code(uid: int, code: str) -> None:
    if not waiting_for_code(uid):
        raise signin.GarminError("The sign-in timed out. Please start again.")
    attempt = _pending[uid][1]
    try:
        tokens = attempt.submit_mfa(code)
    except signin.GarminError:
        if not attempt.waiting_for_mfa:         # not just a wrong code: start again
            _drop_pending(uid)
        raise
    _drop_pending(uid)
    _save(uid, tokens)


def cancel(uid: int) -> None:
    _drop_pending(uid)


def disconnect(uid: int) -> None:
    _drop_pending(uid)
    with get_session() as s:
        row = s.exec(select(GarminLink).where(GarminLink.uid == uid)).first()
        if row:
            s.delete(row)
            s.commit()


def token(uid: int) -> str:
    """The access token of `uid`, renewed first when due (blocking - call it
    from a thread). Raises GarminUnavailable."""
    with _locks.setdefault(uid, threading.Lock()):
        row = link_of(uid)
        if not row:
            raise GarminUnavailable(N_("Your Garmin account is not connected. "
                                       "Connect it under Account."))
        try:
            oauth2 = _open(row.oauth2)
            if not signin.needs_renewal(oauth2):
                return oauth2["access_token"]
            oauth2 = _renew(_open(row.oauth1))
        except InvalidToken as exc:
            raise GarminUnavailable(N_("The Garmin connection can't be read any more "
                                       "(new secret key?). Connect it again under "
                                       "Account.")) from exc
        except signin.GarminError as exc:
            with get_session() as s:
                row = s.get(GarminLink, row.id)
                row.error = str(exc)
                s.add(row)
                s.commit()
            raise GarminUnavailable(N_("Garmin refused to renew the access. Connect it "
                                       "again under Account.")) from exc
        with get_session() as s:
            row = s.get(GarminLink, row.id)
            row.oauth2, row.error = _seal(oauth2), ""
            s.add(row)
            s.commit()
        return oauth2["access_token"]
