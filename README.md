# MyGPXContainer

A self-hosted home for your GPX routes. Upload GPX files or take routes over
from a share link (Komoot, Garmin Connect, any link to a GPX file), see them on
a map with an elevation profile, find them by sport, distance, climbing or
place, and send them as courses to your own Garmin Connect account and on to
your Garmin devices. Optionally it suggests round trips and A-to-B routes from
your own routing service.

For one person or for several: everyone has their own routes and folders,
and a route can be shared as a copy. The interface is in English and German.

An independent, unofficial project, not affiliated with or endorsed by Garmin
or Komoot.

## What it does

- **Routes:** upload GPX (up to 50 at once) or paste a share link - a Komoot
  tour, a Garmin Connect course (yours or a public one), any link to a GPX
  file. The file is kept byte for byte; distance, climbing and shape are
  computed from it.
- **Direction:** arrows on every map and in the list show which way a route
  goes; "Reverse direction" turns it round (start and finish, climbs, the
  download and Garmin follow) - the uploaded file stays as it is. "Copy"
  makes a second route from one, e.g. to keep both directions.
- **Way types and surfaces (optional):** which share of a route is cycleway,
  minor road, road, main road, track, path, footway - and asphalt, paved,
  cobbles, gravel, unpaved - as bars and a list; tap one and its stretches
  light up on the map. Worked out from OpenStreetMap by your own routing
  service (the same as for the suggestions), so it covers its map regions.
- **Finding:** filters by sport, distance, climbing, terrain, folder and
  "near a place" or "near me", text search, a list and an overview map.
- **Garmin:** "Send to Garmin…" puts one or several routes into your Garmin
  Connect account as private courses (each as the sport you pick) and, if you
  tick them, on to your devices. "My Garmin" shows what is there and on which
  device, and removes courses again. Nothing happens on its own.
- **Suggestions (optional):** round trips or A-to-B routes for a sport,
  distance and profile, computed by your own GraphHopper - your positions
  never leave your server. Stops on the way, as many as you like: searched
  or tapped on a map, reordered by dragging; a round trip passes them in
  order and comes back another way.
- **Sharing:** a copy of a route for another person on the same instance.

## Installing

Pick one of these. All of them keep the data in one directory (`/data` in
the container) - back it up.

| Way | For | Needs |
|---|---|---|
| [A. Docker Compose, built here](#a-docker-compose-built-here) (recommended) | a home server, a VPS, a NAS | Docker with Compose |
| [B. Docker Compose with the published images](#b-docker-compose-with-the-published-images) | the same, without building | Docker with Compose |
| [C. A single `docker run`](#c-a-single-docker-run) | trying it out | Docker |
| [D. Without Docker](#d-without-docker) | development, a machine without Docker | Python 3.12, [uv](https://docs.astral.sh/uv/) |

The round-trip suggestions need the separate routing service, which comes
as a container (A and B, see [below](#round-trip-suggestions-optional)).
Everything else works with every way.

On the first start there is no account: the page asks for a **setup code**
(printed to the app's log, or the one you set as `MGC_SETUP_CODE`) and makes
the first account - the admin. Before you use the app over the internet, put
it behind a reverse proxy with https (see
[Behind a reverse proxy](#behind-a-reverse-proxy)).

### A. Docker Compose, built here

```sh
git clone https://github.com/mskerwiderski/MyGPXContainer
cd MyGPXContainer
cp .env.example .env        # optional: adjust (mode, port, time zone, ...)
docker compose up -d --build
docker compose logs mygpxcontainer | grep "setup code"
```

Open `http://<your server>:8000`. Update later with `git pull` and
`docker compose up -d --build`.

### B. Docker Compose with the published images

Each release is published as images for amd64 and arm64
(`ghcr.io/mskerwiderski/mygpxcontainer`, `...-routing`). Take
`docker-compose.yml` and `.env.example` from the repository (or clone it as
in A), and in `.env`:

```sh
MGC_IMAGE=ghcr.io/mskerwiderski/mygpxcontainer:latest
MGC_ROUTING_IMAGE=ghcr.io/mskerwiderski/mygpxcontainer-routing:latest
```

then `docker compose pull && docker compose up -d`. Update the same way.

### C. A single `docker run`

```sh
docker run -d --name mygpxcontainer -p 8000:8000 -v mygpxcontainer_data:/data \
  -e MGC_TIMEZONE=Europe/Berlin ghcr.io/mskerwiderski/mygpxcontainer:latest
docker logs mygpxcontainer | grep "setup code"
```

(Or build the image yourself: `docker build -t mygpxcontainer .` in the
repository.) No round-trip suggestions this way.

### D. Without Docker

```sh
git clone https://github.com/mskerwiderski/MyGPXContainer
cd MyGPXContainer
uv sync
MGC_DATA_DIR=~/mygpx-data uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The settings below are environment variables here as well. No round-trip
suggestions this way (the routing service needs Java and osmium - run it as
its container if you want them).

### Modes

| `MGC_AUTH` | For | Sign-in |
|---|---|---|
| `single` (default) | one person | one account with a password; no sharing, no user management |
| `local` | family, club, friends | accounts of this app; the admin invites people by a one-time link (People); sharing between them |
| `myauth` | the author's own setup | an external MyAuth service (not published); sign-in, Garmin and the people come from there |

There is no open sign-up. Passwords are stored as scrypt hashes; sessions
are cookies (HttpOnly, SameSite=Lax, Secure behind https).

### Connecting Garmin

Under **Account -> Garmin Connect** you sign in to Garmin once (e-mail,
password, and the code Garmin sends if two-factor sign-in is on). Your Garmin
password goes to Garmin only and is stored nowhere. The app keeps the access
Garmin hands out, encrypted with `MGC_SECRET_KEY` (or, without it, a key it
makes in the data directory). Garmin Connect's API is undocumented; Garmin
may change it at any time.

Courses sent to a device stay there: later changes don't follow them, and
only you can remove them, on the device itself.

### Round-trip suggestions (optional)

The routing service is GraphHopper with OpenStreetMap data from Geofabrik. It
needs memory: a small region (a German state, Greater London) builds with
2-4 GB, all of Germany needed up to ~18 GB during the build and ~3.5 GB while
serving. In `.env`:

```sh
COMPOSE_PROFILES=routing
MGC_ROUTING_URL=http://mygpxcontainer-routing:8989
ROUTING_SERVE_HEAP=2g
ROUTING_IMPORT_HEAP=4g
```

Then `docker compose up -d`, and as admin pick the map regions under
**Maps** (`/admin/routing`). The first build downloads and imports them;
`/suggest` says when the map is ready. The graph is rebuilt every 30 days at
night (`ROUTING_REFRESH_DAYS`, `TZ`).

## Configuration

All settings are environment variables, usually in `.env`
([.env.example](.env.example)).

| Variable | Default | Meaning |
|---|---|---|
| `MGC_AUTH` | `single` | `single`, `local`, `myauth` (see above); `none` = no sign-in at all, for development only |
| `MGC_PORT` | `8000` | port on the host (compose) |
| `MGC_SETUP_CODE` | random, in the log | the code the first-start page asks for |
| `MGC_SECRET_KEY` | key file in the data dir | Fernet key for the stored Garmin access; keep it apart from backups of the data if you can |
| `MGC_TIMEZONE` | `TZ`, else UTC | dates for people without a time zone of their own |
| `MGC_MAX_BODY_MB` | `100` | largest request (uploads) |
| `MGC_ROUTING_URL` | empty | the routing service; empty = no suggestions |
| `MGC_PHOTON_URL` | `https://photon.komoot.io` | address search on `/suggest` |
| `MGC_FOOTER_NOTE` | empty | a line in the footer, e.g. who runs the instance |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | proxies whose `X-Forwarded-For` uvicorn trusts (see below) |
| `MGC_AUTH_URL`, `MGC_AUTH_PUBLIC_PORT`, `MYAUTH_APP_KEY` | | mode `myauth` only |

Data lives in the volume `mygpxcontainer_data` (`/data`): the SQLite database,
the GPX files (content-addressed) and, without `MGC_SECRET_KEY`, the key
file. Back it up; the routing volume can always be rebuilt.

### Behind a reverse proxy

Terminate https at the proxy and forward to port 8000 - with Caddy, for
example:

```
gpx.example.org {
	reverse_proxy localhost:8000
}
```

Set `FORWARDED_ALLOW_IPS` to the proxy's address (or `*` when only the proxy can
reach the container), so that sign-in limits count the real client address
and not the proxy's. The proxy must pass the `Host` header through unchanged
(or set `X-Forwarded-Host`): posts from another site are refused by comparing
`Origin` with it.

## Third-party services

The app talks to these, from the server unless noted:

- **Garmin Connect** (sending courses, devices, Garmin course links) - only
  with each person's own Garmin access.
- **Komoot** (tour share links) - the public tour API, with the share token
  of the link.
- **Open-Meteo geocoding** (the place filter of the list) and **Photon** by
  komoot (address search on `/suggest`) - both have fair-use rules; for
  heavy use run your own Photon (`MGC_PHOTON_URL`).
- **Geofabrik** (map extracts for the routing service).
- In the browser: map tiles from **OpenStreetMap**, **OpenTopoMap** and
  **Esri World Imagery** - mind their tile usage policies.

## Development

Python 3.12, [uv](https://docs.astral.sh/uv/).

```sh
uv sync --extra dev
uv run pytest
uv run ruff check app tests
MGC_AUTH=none uv run uvicorn app.main:app --reload    # no sign-in, development only
```

`docs/plan.md` and `docs/plan-standalone.md` hold the design and its
decisions; `CLAUDE.md` the conventions of the code. `app/access/`,
`app/garmin_api/` and `app/garmin_login/` are copies of shared building
blocks of the author's projects - change them there, not here.

## Licence

MIT, see [LICENSE](LICENSE).
