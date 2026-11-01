"""MyGPXContainer - FastAPI app: login middleware and pages.
UI in English and German, as set in MyAuth (i18n.py)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth, drawing, elevation, pages, routing
from .auth import local as _local_accounts  # noqa: F401 - its pages (modes local, single)
from .config import get_settings
from .db import get_engine, get_session
from .version import __version__

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_engine()
    with get_session() as s:
        routing.setup(s)          # the map regions for the routing container
    _local_accounts.announce_setup()
    # routes still without the elevation model's heights (elevation.py)
    catching_up = asyncio.create_task(elevation.catch_up_loop())
    if get_settings().auth_mode == "none":
        logging.getLogger(__name__).warning("MGC_AUTH=none: NO sign-in - development only")
    yield
    catching_up.cancel()


app = FastAPI(title="MyGPXContainer", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")),
          name="static")


# Every answer (security review 2026-10-31): scripts only from the app's own
# files - no inline code anywhere; styles inline for Leaflet and uPlot; map
# tiles from their https servers; no framing.
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; "
                               "style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; "
                               "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
                               "object-src 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
}


@app.middleware("http")
async def require_login(request: Request, call_next):
    """Who is signed in, and refusing cross-site posts (app/auth/). Bodies
    above MGC_MAX_BODY_MB are refused before anything reads them."""
    size = request.headers.get("content-length", "")
    if size.isdigit() and int(size) > get_settings().max_body_mb * 1024 * 1024:
        return JSONResponse({"detail": "request_too_large"}, status_code=413)
    denied = await auth.gate(request)
    response = denied if denied is not None else await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


@app.get("/healthz")
def healthz():
    return {"status": "ok", "version": __version__}


app.include_router(_local_accounts.router)
app.include_router(drawing.router)
app.include_router(pages.router)
