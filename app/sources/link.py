"""Any other link to a GPX file (a planner's export, a file on a website).

The server fetches it, so the link must not reach into the home network
(SSRF): only ports 80 and 443, every host - also after each redirect - has to
resolve to public addresses only, and the address actually connected to is
checked again (`_get`), so a name that resolves differently the second time
(DNS rebinding) gets nowhere. No proxy from the environment. At most 10 MB,
20 s, 5 redirects; the body has to be GPX."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import unquote, urljoin, urlsplit

import httpx

from .. import gpx
from ..i18n import N_
from . import Fetched, SourceError

MAX_REDIRECTS = 5


async def _public(host: str, port: int) -> bool:
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM)
    except OSError:
        return False
    addrs = {ipaddress.ip_address(i[4][0].split("%")[0]) for i in infos}
    return bool(addrs) and all(a.is_global for a in addrs)


def _connected_to_public(r: httpx.Response) -> bool:
    """The peer of the open connection is a public address."""
    stream = r.extensions.get("network_stream")
    peer = stream.get_extra_info("server_addr") if stream else None
    if not peer:
        return False
    try:
        return ipaddress.ip_address(str(peer[0]).split("%")[0]).is_global
    except ValueError:
        return False


async def _get(url: str) -> tuple[int, dict, bytes]:
    """One request without following redirects: status, headers, body
    (cut off after MAX_BYTES + 1)."""
    async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False) as client:
        async with client.stream("GET", url, headers={"user-agent": "MyGPXContainer"}) as r:
            if not _connected_to_public(r):
                raise SourceError(N_("This link does not lead to a public website."))
            body = b""
            async for chunk in r.aiter_bytes():
                body += chunk
                if len(body) > gpx.MAX_BYTES:
                    break
            return r.status_code, dict(r.headers), body


async def fetch(url: str) -> Fetched:
    pasted = url
    for _ in range(MAX_REDIRECTS + 1):
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise SourceError(N_("Please paste a link starting with https://"))
        port = parts.port or (443 if parts.scheme == "https" else 80)
        if port not in (80, 443) or not await _public(parts.hostname, port):
            raise SourceError(N_("This link does not lead to a public website."))
        try:
            status, headers, body = await _get(url)
        except httpx.HTTPError as exc:
            raise SourceError(N_("{source} is not reachable right now."),
                              source=parts.hostname) from exc
        if status in (301, 302, 303, 307, 308) and headers.get("location"):
            url = urljoin(url, headers["location"])
            continue
        if status != 200:
            raise SourceError(N_("{source} answered with an error ({status})."),
                              source=parts.hostname, status=status)
        return Fetched(data=body, source="url", source_url=pasted,
                       filename=unquote(parts.path.rsplit("/", 1)[-1]))
    raise SourceError(N_("Too many redirects."))
