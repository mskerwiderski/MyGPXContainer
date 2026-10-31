"""Page rendering: one Jinja environment, `_` bound to the request's language,
numbers and dates formatted for it (dates in the user's zone from MyAuth)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader

from . import i18n
from .assets import asset
from .config import get_settings
from .version import __version__

_env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"), autoescape=True)
_env.globals.update(asset=asset, version=__version__)


def lang(request: Request) -> str:
    return i18n.pick(getattr(request.state, "user", None),
                     request.headers.get("accept-language", ""))


def number(language: str, value: float | None, digits: int = 0) -> str:
    if value is None:
        return "–"
    text = f"{value:,.{digits}f}"
    if language == "de":
        text = text.replace(",", " ").replace(".", ",")
    else:
        text = text.replace(",", " ")
    return text


def _zone(request: Request) -> ZoneInfo:
    home = get_settings().timezone
    name = (getattr(request.state, "user", None) or {}).get("timezone") or home
    try:
        return ZoneInfo(name)
    except Exception:
        try:
            return ZoneInfo(home)
        except Exception:
            return ZoneInfo("UTC")


def date(request: Request, language: str, value: datetime | None) -> str:
    """A stored UTC time as a date in the user's zone."""
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    local = value.astimezone(_zone(request))
    return local.strftime("%d.%m.%Y" if language == "de" else "%b %-d, %Y")


def local_path(value: str) -> bool:
    """A path of this app ("/x?y"), never one a browser could take to another
    host: no "//", no backslash ("/\\evil" is "//evil" to browsers), no
    control characters (security review 2026-10-31)."""
    return (value.startswith("/") and not value.startswith("//") and "\\" not in value
            and not any(ord(c) < 32 or ord(c) == 127 for c in value))


def script_json(value) -> str:
    """JSON for a `<script type="application/json">` block, printed with
    |safe: `<`, `>` and `&` as \\u escapes, so a name like
    "</script><script>..." cannot end the block (security review 2026-10-31)."""
    text = json.dumps(value, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render(request: Request, template: str, status_code: int = 200, **context) -> HTMLResponse:
    from . import auth  # auth renders its error pages through here
    language = lang(request)
    html = _env.get_template(template).render(
        request=request, lang=language, _=partial(i18n.gettext, language),
        num=partial(number, language), date=partial(date, request, language),
        account=auth.account(request), admin=auth.is_admin(request),
        sharing=auth.sharing(), people_admin=auth.mode() == "local",
        footer_note=get_settings().footer_note, **context)
    return HTMLResponse(html, status_code=status_code)


def error(request: Request, status_code: int, title: str, text: str = "") -> HTMLResponse:
    """A message page inside the shell; title and text are English keys."""
    return render(request, "message.html", status_code, title=title, text=text)
