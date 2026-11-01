"""Share links: a URL in, a GPX file plus name, description and suggested
sports out. Komoot tours, Garmin Connect courses, any other GPX URL.
Each source module has one network mock point (`_get`/`_get_json`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from ..i18n import N_


@dataclass
class Fetched:
    data: bytes
    source: str            # komoot | garmin | garmin_activity | url
    source_url: str
    external_id: str = ""
    name: str = ""          # the source's own name, wins over the file's
    filename: str = ""      # last resort for the name
    description: str = ""
    sports: list[str] = field(default_factory=list)


class SourceError(Exception):
    """`text` is an English key with `{fields}`, translated where shown."""

    def __init__(self, text: str, **values):
        super().__init__(text)
        self.text, self.values = text, values


def kind(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    if host == "komoot.com" or host.endswith((".komoot.com", ".komoot.de")) or host == "komoot.de":
        return "komoot"
    if host == "connect.garmin.com":
        return "garmin"
    return "url"


async def fetch(url: str, uid: int | None, lang: str = "en") -> Fetched:
    from . import garmin, komoot, link
    url = url.strip()
    if urlsplit(url).scheme not in ("http", "https"):
        raise SourceError(N_("Please paste a link starting with https://"))
    k = kind(url)
    if k == "komoot":
        return await komoot.fetch(url)
    if k == "garmin":
        return await garmin.fetch(url, uid, lang)
    return await link.fetch(url)
