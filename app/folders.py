"""Folders: each user has their own (Michael 2026-10-29), each of their routes
is in exactly one. The default folder ("General") is no row: routes with
folder_id None are in it, it can neither be renamed nor deleted. Deleting a
folder moves its routes there. The owner is kept by uid AND username, like
on routes."""

from __future__ import annotations

from sqlalchemy import func
from sqlmodel import Session, select

from .i18n import N_
from .models import Folder, Route
from .routes import owned_by, owner

DEFAULT_NAME = N_("General")


class FolderError(ValueError):
    """`text` is an English key."""

    def __init__(self, text: str):
        super().__init__(text)
        self.text = text


def _mine(user: dict | None) -> tuple:
    uid, username = owner(user)
    return (Folder.created_by_uid == uid if uid is not None else Folder.created_by_uid.is_(None),
            Folder.created_by_username == username)


def all_folders(session: Session, user: dict | None) -> list[Folder]:
    return sorted(session.exec(select(Folder).where(*_mine(user))),
                  key=lambda f: f.name.casefold())


def get_own(session: Session, user: dict | None, folder_id: int) -> Folder | None:
    """The user's folder with this id; None also for someone else's."""
    folder = session.get(Folder, folder_id)
    return folder if folder and (folder.created_by_uid, folder.created_by_username) == owner(user) else None


def counts(session: Session, user: dict | None) -> dict[int | None, int]:
    rows = session.exec(select(Route.folder_id, func.count())
                        .where(*owned_by(user)).group_by(Route.folder_id))
    return {fid: n for fid, n in rows}


def _check_name(session: Session, user: dict | None, name: str, skip_id: int | None = None) -> str:
    name = " ".join(name.split())[:80]
    if not name:
        raise FolderError(N_("A folder needs a name."))
    taken = {f.name.casefold() for f in all_folders(session, user) if f.id != skip_id}
    if name.casefold() in taken:
        raise FolderError(N_("There is already a folder with this name."))
    return name


def create(session: Session, name: str, user: dict | None) -> Folder:
    uid, username = owner(user)
    folder = Folder(name=_check_name(session, user, name), created_by_uid=uid,
                    created_by_username=username)
    session.add(folder)
    session.commit()
    session.refresh(folder)
    return folder


def rename(session: Session, folder: Folder, name: str, user: dict | None) -> None:
    folder.name = _check_name(session, user, name, skip_id=folder.id)
    session.add(folder)
    session.commit()


def delete(session: Session, folder: Folder) -> int:
    """Removes the folder; its routes go to the default folder. Returns how many."""
    moved = list(session.exec(select(Route).where(Route.folder_id == folder.id)))
    for r in moved:
        r.folder_id = None
        session.add(r)
    session.delete(folder)
    session.commit()
    return len(moved)


def valid_id(session: Session, user: dict | None, value) -> int | None:
    """A folder id from a form: None for the default folder, anything unknown
    or someone else's folder."""
    try:
        fid = int(value)
    except (TypeError, ValueError):
        return None
    return fid if fid and get_own(session, user, fid) else None
