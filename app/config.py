"""App configuration from environment variables with local-first defaults.

Everything persistent lives under DATA_DIR (the Docker volume)."""

from __future__ import annotations

import os
from pathlib import Path

AUTH_MODES = ("myauth", "local", "single", "none")


class Settings:
    def __init__(self) -> None:
        self.data_dir = Path(os.environ.get("MGC_DATA_DIR", "./data")).expanduser().resolve()
        # Login via MyAuth: internal URL for GET /api/session; the public
        # login lives on the same host as this app, on this port.
        self.auth_url = os.environ.get("MGC_AUTH_URL", "").rstrip("/")
        # Who signs in (app/auth/, docs/plan-standalone.md): myauth | local |
        # single | none (development and tests only - no sign-in at all).
        # Unset: myauth if MGC_AUTH_URL is set, else single - never open.
        self.auth_mode = (os.environ.get("MGC_AUTH", "").strip().lower()
                          or ("myauth" if self.auth_url else "single"))
        if self.auth_mode not in AUTH_MODES:
            raise ValueError(f"MGC_AUTH must be one of {', '.join(AUTH_MODES)}")
        if self.auth_mode == "myauth" and not self.auth_url:
            raise ValueError("MGC_AUTH=myauth needs MGC_AUTH_URL")
        self.auth_public_port = int(os.environ.get("MGC_AUTH_PUBLIC_PORT", "1000"))
        # App key from MyAuth's APP_KEYS (only in .env): fetches a user's Garmin
        # token (auth.garmin_token). Empty = no Garmin (share links, sync).
        self.myauth_app_key = os.environ.get("MYAUTH_APP_KEY", "")
        # The elevation model's tiles (elevation.py, dem block): rebuildable cache.
        self.dem_dir = Path(os.environ.get("MGC_DEM_DIR", str(self.data_dir / "dem")))
        # The time zone for dates when the user has none of their own.
        self.timezone = os.environ.get("MGC_TIMEZONE") or os.environ.get("TZ") or "UTC"
        # Own GraphHopper for the loop suggestions (routing/, suggest.py) and the
        # volume shared with it (regions.json, status.json - routing.py).
        # Empty URL = no suggestions; the Docker image sets both.
        self.routing_url = os.environ.get("MGC_ROUTING_URL", "").rstrip("/")
        self.routing_dir = Path(os.environ.get("MGC_ROUTING_DIR", str(self.data_dir / "routing")))
        # Address search while typing on /suggest (places.py): Photon, OSM-based.
        self.photon_url = os.environ.get("MGC_PHOTON_URL", "https://photon.komoot.io").rstrip("/")
        # Modes local/single: the code the first-start page asks for. Empty =
        # a random one in the data dir, written to the log (auth/local.py).
        self.setup_code = os.environ.get("MGC_SETUP_CODE", "").strip()
        # Largest request body (uploads), in MB.
        self.max_body_mb = int(os.environ.get("MGC_MAX_BODY_MB", "100"))
        # A line in the footer (e.g. who runs this instance); empty = none.
        self.footer_note = os.environ.get("MGC_FOOTER_NOTE", "")

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
