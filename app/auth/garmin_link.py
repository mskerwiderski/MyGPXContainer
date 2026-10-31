"""Garmin Connect for own accounts (modes local and single, v0.20.0).

Signing in and keeping the access are the MyCommons block `garmin_login`
(app/garmin_login/ is a copy - never edit it here; `MyCommons/sync.sh
garmin_login app`), the same one MyAuth uses: `signin` speaks Garmin's
protocol, `keeper` holds a sign-in waiting for its MFA code (10 min, a
browser's twin submission of the code counts as done), seals the tokens and
renews the access token one at a time per uid. What stays here:
- the tokens per uid in `GarminLink`, sealed with a Fernet key: MGC_SECRET_KEY,
  else `secret.key` in the data dir, made on first use (readable by the app
  only). Losing the key means connecting Garmin again;
- the texts for the account page and for the rest of the app
  (`GarminUnavailable`).
The password goes to Garmin once and is stored nowhere. Mock points of the
tests: `_signin()` (a SignIn) and `_renew(oauth1)`.
"""

from __future__ import annotations

import os

from sqlmodel import select

from ..config import get_settings
from ..db import get_session
from ..garmin_login import keeper, signin
from ..i18n import N_
from ..models import GarminLink, now_utc
from . import GarminUnavailable

_sealer: keeper.Sealer | None = None


def _signin() -> signin.SignIn:
    return signin.SignIn()


def _renew(oauth1: dict) -> dict:
    return signin.renew(oauth1)


_signins = keeper.SignIns(factory=lambda: _signin())
_renewer = keeper.Renewer(renew=lambda oauth1: _renew(oauth1))


def _key() -> keeper.Sealer:
    global _sealer
    if _sealer is None:
        s = get_settings()
        key = os.environ.get("MGC_SECRET_KEY", "").encode()
        if not key:
            path = s.data_dir / "secret.key"
            if not path.exists():
                from cryptography.fernet import Fernet
                s.ensure_dirs()
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(Fernet.generate_key())
            key = path.read_bytes().strip()
        _sealer = keeper.Sealer(key)
    return _sealer


def _seal(value: dict) -> str:
    return _key().seal(value)


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


def waiting_for_code(uid: int) -> bool:
    return _signins.waiting(uid)


def connect(uid: int, email: str, password: str) -> bool:
    """Signs in to Garmin. True: connected; False: Garmin wants the MFA code
    (`submit_code`). Raises signin.GarminError with a text for the user."""
    tokens = _signins.start(uid, email, password)
    if tokens is None:
        return False
    _save(uid, tokens)
    return True


def submit_code(uid: int, code: str) -> None:
    tokens = _signins.submit(uid, code)
    if tokens is not None:              # None: a twin submission connected already
        _save(uid, tokens)


def cancel(uid: int) -> None:
    _signins.cancel(uid)


def disconnect(uid: int) -> None:
    _signins.cancel(uid)
    with get_session() as s:
        row = s.exec(select(GarminLink).where(GarminLink.uid == uid)).first()
        if row:
            s.delete(row)
            s.commit()


def token(uid: int) -> str:
    """The access token of `uid`, renewed first when due (blocking - call it
    from a thread). Raises GarminUnavailable."""
    if not link_of(uid):
        raise GarminUnavailable(N_("Your Garmin account is not connected. "
                                   "Connect it under Account."))

    def load() -> tuple[dict, dict | None]:
        row = link_of(uid)
        oauth1 = _key().open(row.oauth1) if row else None
        if oauth1 is None:
            raise GarminUnavailable(N_("The Garmin connection can't be read any more "
                                       "(new secret key?). Connect it again under "
                                       "Account."))
        return oauth1, _key().open(row.oauth2)

    def save(oauth2: dict) -> None:
        with get_session() as s:
            row = s.exec(select(GarminLink).where(GarminLink.uid == uid)).one()
            row.oauth2, row.error = _seal(oauth2), ""
            s.add(row)
            s.commit()

    try:
        return _renewer.fresh(uid, load, save)["access_token"]
    except signin.GarminError as exc:
        with get_session() as s:
            row = s.exec(select(GarminLink).where(GarminLink.uid == uid)).first()
            if row:
                row.error = str(exc)
                s.add(row)
                s.commit()
        raise GarminUnavailable(N_("Garmin refused to renew the access. Connect it "
                                   "again under Account.")) from exc
