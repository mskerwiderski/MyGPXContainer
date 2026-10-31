# MyGPXContainer – Plan

As of 2026-10-29. Route collection for MyAuth users - each user has their own
(since v0.11.0, before that one shared collection): upload GPX routes or take
them over from a share link, describe them, find them by sport, share a copy
with another user and send them as a course to your own Garmin Connect and devices.

## Frame (from the portfolio conventions)

- **Stack:** Python/FastAPI, Jinja templates, SQLite (SQLModel), Docker - like
  MyDocContainer/MFC. Design system **msk-ui** (copy in `app/static/ui/`),
  light/dark following the system, tab bar on mobile.
- **UI language: English and German following MyAuth** (`language` from
  `/api/session`, fallback English). Pattern MyGarminLiveTrack
  (`garmin_livetrack/i18n.py`): English is source and key (`_("Distance")` in
  Python/Jinja, `T("…")` in JS with an embedded catalogue), German catalogue
  `DE`; if a text is missing, English appears; `tests/test_i18n.py` checks
  that every marked text is translated. `<html lang>` follows the language.
  Numbers/dates formatted per language (decimal comma), times in the zone from
  MyAuth. User content (name, description) is NOT translated. Enter the
  exception in the project map (UI language "de + en following MyAuth").
- **Operation:** a Docker container, port 8000 internally, named volume
  for the data (backed up), behind a reverse proxy; the author's instance
  is private (tailnet/LAN only).
- **Sign-in:** MyAuth (`/api/session?app=mygpxcontainer`, cookie
  `sso_session`). No user management of its own.
- CI (ruff E9/F, pytest, docker build, gitleaks), version in `app/version.py`,
  `/healthz` reports it.

## MyAuth - what is needed there (configuration only, no code)

MyAuth can already do everything (checked in the MyAuth code):

- Garmin access lives **per user** in MyAuth; everyone connects their account
  themselves under `/connections` (incl. MFA). The card appears as soon as an
  enabled app has `garmin: true`.
- Token per user: `GET /api/internal/garmin/token?uid=<uid>&app=mygpxcontainer`
  with `Authorization: Bearer <MYAUTH_APP_KEY>`, only from the Docker network.
  MyAuth renews by itself; errors `404 not_connected`, `502 garmin_refused`.
- That the token may **create** courses is proven live (2026-10-27,
  "Gravel 90" through MFC with the same MyAuth token).

To-dos for Michael (secrets/admin):
1. `APPS` entry in MyAuth (its compose override):
   `{"key": "mygpxcontainer", "name": "MyGPXContainer", "port": 1016,
   "garmin": true, "description": {...}}`
2. Secret in MyAuth's `APP_KEYS` and as `MYAUTH_APP_KEY` in
   `~/srv/mygpxcontainer/.env`.
3. Enable the app per user (`/admin/users/{uid}`); `app_admin` for Michael.

Deliberate trust decision: MyAuth knows no consent per app - every app with
`garmin: true` may fetch the token of every enabled user. Fine for family and
friends; before the first sync the UI says what the app does in Garmin
("creates and updates courses, nothing else").

## Domain model

**Route** (until v0.10 visible to all users; since v0.11.0 its owner's own,
see "Routes per user" below):

| Field | Content |
|---|---|
| `id`, `uid` (stable, uuid4) | uid for the Garmin mark and links |
| `name`, `description` | required, or free text (line breaks stay, no Markdown) |
| `sports` | multiple choice from Garmin's outdoor sports of the groups Run, Walk, Bike (see below) - a route can be Gravel AND MTB; when sending the user picks one |
| `gpx_sha` | file content-addressed in the store `ab/cd/<sha>.gpx` (the original stays unchanged) |
| derived | `distance_m`, `ascent_m`, `descent_m`, `min/max_ele`, `start_lat/lon`, `bbox`, `loop` (start≈finish), `point_count` |
| `source` | `upload` \| `komoot` \| `garmin` \| `url`, plus `source_url`, `external_id` |
| `created_by_uid` + `created_by_username`, `created_at`, `updated_at` | username as well, because a rebuilt MyAuth can reuse uids (pattern MCPServerGarminConnect `users.py`) |

**Sports = Garmin activity types** (Michael 2026-10-27: all sub-sports of
Run/Walk/Bike). Garmin's `typeKey` is stored, so sending needs no mapping.
The list comes once from `GET activity-service/activity/activityTypes` and is
then fixed in the code (`sports.py`, with type id, group and label en/de) - a
new Garmin sport is a code change, not a runtime fetch. Groups:
- **Run:** running + children (trail_running, track_running, ultra_run, …)
- **Walk:** walking + children, plus hiking (a main sport of its own at
  Garmin, Walk by subject)
- **Bike:** cycling + children (road_biking, gravel_cycling, mountain_biking,
  cyclocross, e-bike variants, …)
Indoor/virtual (treadmill, indoor_cycling, virtual_ride, …) stay out - a
route is always outdoors. The exact list is fetched live in milestone 2 and
recorded here. Filter in the list: group OR a single sport.

**GarminCourse** (per route × user, since v0.17.0 = a course that is in
Garmin Connect): `route_uid, uid, username, name, course_id, activity_type,
synced_hash, synced_at, error, pushed_to, pushed_old`. `synced_hash` = hash
over GPX SHA + name + description + type → "changed" when the route has
changed since it was sent. The row outlives a deleted route (no FK) - its
course stays in Garmin Connect until the user removes it.

**Rights:** until v0.10 everyone saw and downloaded everything; edit/delete
only the creator and `app_admin` (Michael 2026-10-27). Since v0.11.0 every
user sees and changes only their own routes and folders (Michael 2026-10-29).

## Features

### 1. Creating routes
- **Upload:** one or more `.gpx` (up to 50 per upload). Own parser on
  `defusedxml` (`app/gpx.py`, no gpxpy); accepts `trk` and `rte`, all
  segments and tracks are joined in file order (implemented in v0.2.0
  instead of asking back - add later if needed).
  Limits: 10 MB, ≥ 2 points, (0,0) and invalid coordinates dropped (lesson
  from MFC). Timestamps stay in the file but play no role.
- **Share link** (one field, recognised by host):
  - **Komoot** tour (`komoot.com/…/tour/<id>?share_token=…`): public
    API `api/v007/tours/<id>?share_token=…&_embedded=coordinates` (tried
    live) → name, suggested sport (`mtb_easy` → gravel_cycling,
    `racebike` → road_biking, `touringbicycle` → cycling, `mtb`/
    `mtb_advanced` → mountain_biking, `e_*` → e-bike counterpart, `jogging` →
    running, `hike` → hiking, `mountaineering` → hiking, `trail_running`
    if present), coordinates with elevation → build the GPX. Private tours
    without `share_token` do not work - the error message says so.
  - **Garmin Connect** course (`connect.garmin.com/modern/course/<id>`): with
    the creating user's token `GET course-service/course/<id>` or
    `…/gpx/<id>`.
  - **Direct GPX URL** (RideWithGPS export, own files …): download with a
    size limit, timeout, only http(s), no private IP targets (SSRF).
  - Possible later: Strava routes (through MyAuth's Strava, own routes only),
    RideWithGPS by id.
- **Duplicates:** same GPX SHA → hint to the existing route; the same
  source (Komoot id) as well.
- Preview before saving: map, figures, suggested sport.

### 2. Maintaining routes
- Detail page: map (Leaflet + OSM, base map like MFC), elevation profile
  linked to the map, figures, description, source, creator, GPX download,
  state in the user's own Garmin Connect.
- Edit: name, description, sports, replace the GPX (new version →
  `synced_hash` outdated). Delete with confirmation.
- Elevations: from the GPX. If missing (some exports), v1 without elevations;
  later DEM (Copernicus GLO-30 like MFC's `elevation_correct`). Ascent = plain
  sum of the elevation steps like Komoot/Garmin (Gravel 90: 224 m; every
  smoothing came out 10-20 % lower). Recorded tracks with noisy elevation
  therefore come out too high - the DEM would be the remedy.

### 3. Finding
- List/map grid with filters: sport, distance from-to, ascent, loop, creator,
  text search (name/description, FTS5), "near me" / start within a radius
  around a place (Open-Meteo geocoding like MFC).
- Overview map with all starts (clusters), click → route.
- Marker "in my Garmin" per route.

### 4. Garmin (per user, own account only)
v0.17.0 (Michael 2026-10-31): the earlier model - mark routes, a sync brings
the account in line - was not clear to a normal user (marks waited for a sync
nobody started, deleted routes took their courses along unseen, courses
deleted in Garmin came back). Now nothing happens on its own:
- **Send** ("Send to Garmin…" on a route or for a selection in the list): a
  page with every route and its sport, Garmin Connect always, devices ticked
  on top (one to all). A route already there is kept if unchanged, replaced
  (delete + create, new course id) if changed or sent as another sport.
- **My Garmin**: what the app put into Garmin Connect, as Garmin has it on
  each visit, with the devices each course went to (older versions marked).
  Remove selected or all - also the courses of deleted routes. Courses
  deleted in Garmin drop out and are not made again.
- **Devices go one way** (hint on both pages): Garmin can put a course on a
  device but neither update nor remove it there.
- Per course (tried live): `POST course-service/course/import` (only parses)
  → interpolate the elevations from the GPX over the distance (Garmin leaves
  them empty) → set fields (`activityTypePk`, `rulePK` 2 = private, WGS84,
  `elevationSource` 3, bounding box, gain/loss from our calculation) →
  `POST course-service/course`. The description carries the mark
  `MGC:route=<uid>` (pattern MFC `MFC:tp=`); only marked courses are deleted.
- Device: a device message pointing at the course's FIT, like "Send to
  device" in Garmin Connect.
- Garmin errors of one course do not stop the others; `not_connected` from
  MyAuth → hint with a link to MyAuth `/connections`.
- **Other direction (v2):** list the user's own Garmin courses and take them
  over as routes (`course/owner/<displayName>`); the author has dozens of courses there.

### 5. Interfaces (later)
- REST (`/api/routes…`) and maybe MCP (search routes, fetch GPX) following
  the MFC pattern - only when needed.

## Architecture

```
app/
  main.py          FastAPI, routes, templates, /healthz
  version.py
  config.py        Settings (MYAUTH_URL, MYAUTH_APP_KEY, STORE_DIR, …)
  myauth.py        session check (uid, username, app_admin, timezone, impersonated_by)
  garmin_token.py  token per uid through MyAuth (mock point _fetch)
  garmin_courses.py course API: import, create, update, delete, get (httpx)
  gpx_io.py        parse, clean, figures, write GPX
  sources/         komoot.py, garmin.py, url.py (share links)
  models.py, db.py SQLModel + migrations
  store.py         content-addressed GPX storage
  templates/, static/ui (msk-ui copy), static/app.css, static/*.js
tests/              pytest, fakes for MyAuth/Garmin/Komoot (no network in tests)
```

## Milestones

1. **Scaffold** - repo, FastAPI, msk-ui shell, MyAuth sign-in, i18n en/de,
   `/healthz`, Dockerfile/Compose, CI, README/CLAUDE.md. Deploy on the author's
   server (reverse proxy block, MyAuth entry) - empty app
   reachable. ✔ v0.1.0
2. **Routes** - upload, parser, store, list, detail with map and profile,
   edit, delete, download, rights. ✔ v0.2.0
3. **Share links** - Komoot, Garmin course, GPX URL; duplicate check. ✔ v0.3.0
4. **Garmin sync** - selection, reconciliation (create/update/remove),
   status ✔ v0.4.0 (a changed route = new course by delete + create, no
   PUT); "Gravel 90" as the first live test (adopt the existing course
   526970098 instead of a duplicate).
5. **Finding & polish** - filters, text search, overview map, radius search,
   mobile ✔ v0.5.0. Deviating: text search in Python instead of FTS5
   (hundreds of routes; casefold, every word must match). The overview map
   shows the routes as lines (v0.5.1: only start points were useless when all
   routes start at home). Plus: buttons and filters without reloading
   (Michael 2026-10-27).
6. **Optional** - import Garmin courses, DEM elevations, REST/MCP,
   waypoints/course points, favourite on Garmin.
7. **Routes per user, sharing as a copy** ✔ v0.11.0 (see below).
8. **Round-trip suggestions** - three loops from the user's position for a
   sport, distance and profile; own GraphHopper on the server, map regions
   managed by the admin ✔ v0.12.0 (see below).

## Risks

- **Komoot's and Garmin's course APIs are unofficial.** Encapsulate both
  (`sources/komoot.py`, `garmin_courses.py`), report errors clearly; uploading
  the GPX always remains possible.
- Garmin rate limits with "Sync all": sequential, with pauses.
- Privacy: routes reveal where people live (start at the front door). Until
  v0.10 all signed-in users saw everything; since v0.11.0 only the owner and
  whoever they shared a copy with. Nothing is public.

## After milestone 5 (Michael 2026-10-27)

- Naming scheme `<Start> via <Place> <km>k <hm>hm` (loop) or `<Start> to
  <Finish> …` (A→B), runs with one decimal; existing routes renamed once
  (old names in the description).
- Tags other than sport only automatic: loop/A→B and profile flat
  (< 7 hm/km) / hilly (7-15) / mountainous (≥ 15), filterable (v0.7.0).
- Every tile shows the route as a small sketch (`gpx.sketch`).
- Swipe to delete on the phone (v0.6.0).
- Folders (shared, default folder "Allgemein") and multi-select: mark/unmark
  for Garmin (takes effect with the next sync), move to a folder (v0.8.0).
- A single route can be sent to a device of choice (Edge, fenix …); if it is
  not in Garmin Connect yet, it is created first. The sync itself sends
  nothing to devices (v0.9.1, instead of automatically in v0.9.0).
- Delete the selected routes in the selection mode, with a question first
  (Michael 2026-10-30, v0.13.0).

## Routes per user, sharing as a copy (v0.11.0, Michael 2026-10-29)

"Defaultmäßig sieht ein User nur die eigenen Routen. Ein User kann aber eine
Route mit einem anderen User teilen. Sie wird dann geclont." (By default a
user sees only their own routes; a user can share a route with another user,
who then gets a clone.)

- **Visibility:** routes and folders belong to their owner (`created_by_*`,
  uid + username). Every page and action goes through the owner check;
  someone else's route or folder answers 404, so nobody learns it exists.
  Duplicates are checked within one user's routes; two users may hold the
  same file (stored once). The list filter "Added by" became "From" (me /
  shared by …).
- **Sharing:** "Share…" on the route and in the selection bar opens
  `/routes/share`; the user ticks one or more people and each gets a copy in
  their default folder, marked "Shared by <name> on <date>" (`shared_by_*`,
  `shared_from`, `shared_at`). The copy is independent: later changes on
  either side stay there. Whoever has the route already (same file, same
  Komoot tour/Garmin course, an earlier copy) gets no second one.
- **Who can be picked:** MyAuth lists the active users with the app -
  `GET /api/internal/members` (MyAuth v0.57.0, app key, Docker network only,
  APPS flag `"members": true`). MGC keeps no user list of its own.
- **Garmin:** only own routes can be picked; the sync ignores rows whose route
  is not the user's. Deleting a course accepts any `MGC:route=` mark.
- **Migration (once, on start of v0.11.0):** every route stays with its
  creator. Whoever had someone else's route marked for Garmin gets a copy of
  it, and their Garmin row points to the copy - the course in Garmin stays
  untouched (same hash, no rebuild). Routes a user had put into someone else's
  folder go to a same-named folder of their own. Everything else is from then
  on only visible to its owner.

Decisions (Michael 2026-10-29, the recommendations taken over):
1. Recipient list from MyAuth (new endpoint), not from users MGC has seen.
2. `app_admin` also sees only their own routes (privacy: routes show where
   people live); an "all users" view can come later.
3. A shared copy lands in the receiver's default folder, with "shared by" and
   a "From" filter.
4. Migration as above: own routes stay, Garmin picks of others' routes become
   copies.

## Round-trip suggestions (v0.12.0, 2026-10-30)

"Der User bekommt 3 Rund-Routen vorgeschlagen mit Startpunkt seiner Position.
Er muss nur angeben: Sportart, Distanz, Profil." (The user gets three loop
suggestions starting at their position; they only give sport, distance and
profile.)

### Trial run (2026-10-30, done)

GraphHopper 11.1 with Bavaria on the author's server (test container `gh-probe`,
`~/srv/gh-probe`, stopped), six cases from Starnberg station and Lenggries:
- Import 4.5 min, graph 513 MB, elevation (CGIAR) 107 MB, ~4 GB RAM. Germany
  is ~5x: ~3 GB graph, ~25 min import, ~10 GB RAM while importing.
- `algorithm=round_trip` in flexible mode: 0.1-1 s per loop, 12 candidates
  (one per 30° heading) in at most 1 s. `round_trip.seed` barely changes a
  loop with a fixed heading - the heading gives the variety.
- Distance mostly within 10 %. The profile wish works (road bike hilly
  700-810 hm on 80 km, MTB mountainous up to 1,555 hm on 41 km).
- Without per-sport rules, gravel ran on residential streets (10 % unpaved)
  and MTB/hiking up to 26 % on state roads. With the rules below gravel came
  to 34-39 % unpaved (OSM often lacks the surface, the real share is higher)
  and 0 % big roads, MTB/hiking at most 4 %. Road bike 15-26 % state roads -
  fine (Michael).
- Result page with maps and GPX: `~/Files/MyGPXContainer/probelauf-rundkurse/`.
- Germany with the routing container (2026-10-30): download 2 min (Geofabrik
  redirects big extracts to a mirror, the md5 is only there), import 37 min,
  graph 2.7 GB, **serving 3.4 GB RAM**. The import in the Java heap peaked at
  ~18 GB next to the serving graph -> imports now use memory-mapped files
  (and low CPU priority). Disk 7.5 GB with the extract -> extracts are
  deleted after a build (~3 GB). A cloud API instead (Michael's question):
  openrouteservice limits round trips to 100 km and 40 requests a minute,
  GraphHopper's free plan lacks the flexible mode, and both would get the
  start = the front door - so self-hosted stays.

### What the user does

"Suggest a loop" next to "Add route" (list and `/routes/new`) opens
`/suggest`:
- **Start:** "My location" (browser geolocation, like "Near me"), or a place
  (the existing Open-Meteo search).
- **Sport:** the MGC sports that have an engine profile (table below).
- **Distance** in km (number field plus chips: bike 30/50/80/100, run
  5/10/15/21, walk 5/10/15/20).
- **Profile:** flat / hilly / mountainous (segmented control).
- After 1-3 s: a map with three loops in three colours and three cards (km,
  hm, profile, unpaved share, sketch). "Take over" makes a normal route of
  the user's: source `generated`, the sport as its only sport, name
  "Loop 52k 340hm" (with a searched place: "<Place> loop 52k 340hm"),
  description "Suggested on <date>: Gravel, flat". Then Garmin, devices and
  sharing as for every route.
- "Take over" sends the parameters (start, sport, km, profile, heading), not
  the line: the server computes that loop again (same parameters, same loop)
  and keeps no state between the two requests.
- No suggestion possible: start outside the map ("No map for this area yet -
  an admin can add it"), routing service down or building for the first time
  ("Suggestions are not available right now").

### How the three are chosen (`app/suggest.py`)

1. 12 requests in parallel (headings 0, 30, … 330), `round_trip.distance` =
   the wish, `ch.disable`, elevation, path details `surface` and
   `road_class`, and a per-request custom model = profile wish + sport rules.
2. Profile wish: flat -> slopes ≥ 3 % ×0.7, ≥ 6 % ×0.3; hilly -> flat edges
   (< 2 %) ×0.7; mountainous -> edges under 3 % ×0.4.
3. Sport rules: gravel - primary/trunk/secondary ×0.2, tertiary and
   residential ×0.6, unpaved surfaces and tracks ×1.5; MTB - big roads ×0.2,
   tertiary/residential ×0.6; hiking - big roads and tertiary ×0.2,
   residential ×0.6; running - big roads and tertiary ×0.3, tracks/paths/
   footways ×1.3; road bike - primary/trunk ×0.3; cycling - big roads ×0.4.
4. Per candidate: km and hm with `gpx.stats` (as on every route), profile with
   the sport's limits, share run twice (out and back on a ~30 m grid), unpaved
   share, big-road share.
5. Score = 2 × distance error + 1 per profile step off + 1.5 × run-twice
   share; gravel/MTB/hiking/running + 2 × big-road share; gravel - unpaved
   share; road bike + 3 × unpaved share.
6. Best first; the next only if its direction (start -> centre) differs by
   ≥ 60° and it shares < 40 % of its grid cells with those chosen. Where the
   terrain cannot give the profile, the closest ones come with a note
   ("It does not get steeper around here").

| MGC sport | Engine profile |
|---|---|
| road_biking | racingbike |
| gravel_cycling, cyclocross | gravel (own model, `routing/models/gravel.json`) |
| mountain_biking, e_bike_mountain | mtb |
| cycling, e_bike_fitness | bike |
| running, street_running | foot |
| trail_running, hiking | hike |
| walking, casual_walking, speed_walking | foot |

Not offered: track/downhill/enduro/BMX/hand/recumbent cycling, track/ultra/
obstacle runs.

### Profile limits per sport (Michael 2026-10-30)

Bikes keep 7 / 15 hm per km for hilly / mountainous; on foot (Run and Walk
groups) 20 / 50. `sports.profile(distance, ascent, sport_keys)`: a route
counts as on foot if none of its sports is a bike sport. This applies to the
suggestions AND to the profile tags and the profile filter of the list.

### Routing service (`routing/` in this repo)

- Own image: `eclipse-temurin:21-jre` + `osmium-tool` + GraphHopper 11.1 jar
  (pinned, checksum) + `routing/run.py` (Python standard library) + config
  and `gravel.json`. Profiles bike, racingbike, mtb, gravel, foot, hike;
  flexible mode only (no CH/LM); elevation `multi` (CGIAR + GMTED, so also
  north of 60°); motorways/trunks not imported.
- Compose: second service `mygpxcontainer-routing` in this repo's
  `docker-compose.yml`, network `root_default`, no port, named volume
  `mygpxcontainer-routing` (also mounted into MGC at `/routing`),
  `mem_limit` 16g. MGC finds it at `MGC_ROUTING_URL`
  (`http://mygpxcontainer-routing:8989`).
- `run.py` serves the current graph and rebuilds when `regions.json` (written
  by MGC) differs from the built regions, when an admin asks (`rebuild`
  file) or monthly (fresh OSM): download the Geofabrik extracts (with their
  `.md5`), `osmium merge` into one PBF, `import` into a new graph directory
  while the old one keeps serving, then restart the server on the new graph
  (about a minute without suggestions). It writes `status.json`: state
  (serving / downloading / merging / importing / failed), regions built,
  date, duration, size, last error.
- The volume is rebuildable -> excluded from the backup (infrastructure repo
  `backup/`). The wanted regions live in MGC's database, which is backed up;
  MGC writes `regions.json` on every change and at start.

### Regions for the admin (`/admin/routing`, `app_admin`)

- `app_admin` from MyAuth means something again: managing the map regions
  (`auth.is_admin` comes back; without sign-in everyone, as before).
- List of the wanted regions with state; "Add region" searches Geofabrik's
  index (`index-v1-nogeom.json`, 554 extracts with id, parent, name, PBF URL;
  cached a day), e.g. `canary-islands` for Fuerteventura; "Remove";
  "Rebuild now". A region inside one already wanted (Bayern inside Germany)
  is not added twice.
- Table `RoutingRegion` (geofabrik id, name, added_by uid + username, added
  at). Start values: `germany` and `greater-london` (Michael 2026-10-30).
- Status from `status.json`: what is built, since when, what is being built,
  last error.

### Steps

1. **Routing service:** `routing/` (Dockerfile, `run.py`, config), CI builds
   the image. First on the author's server with Bavaria, then Germany; measure import
   time and memory, rebuild while serving.
2. **Profile limits per sport** in `sports.py`, list tags and filter, tests.
3. **`suggest.py` + `/suggest` + take over**, tests against a fake GraphHopper
   (mock point `suggest._route(body)`); i18n.
4. **`/admin/routing`**, `RoutingRegion`, `regions.json`/`status.json`,
   tests.
5. **Deploy:** compose with both services, Germany as the first region (~25
   min import), MGC v0.12.0; docs (README, CLAUDE.md, this plan); restic
   exclusion in the infrastructure repo; afterwards the test container `gh-probe`
   and `~/srv/gh-probe` go (by hand - the hook keeps deletions on the server
   manual).
6. Michael tries it on the phone from home.

Decisions (Michael 2026-10-30): self-hosted (positions stay on the server, also
after the memory measurement), Germany and London first, the admin adds
countries; extracts deleted after a build; on-foot profile limits 20 / 50 also
for the list; road bike may use state roads as in the trial run.

## Suggestions, second round (v0.14.0, Michael 2026-10-30)

"Wir brauchen auch von-nach; Autovervollständigung bei manueller
Adresseingabe; richtige Benamung bei der Übernahme." (We also need A to B;
autocompletion when typing an address; proper names on take-over.)

- **From A to B:** a switch "Loop | From A to B" on `/suggest`, a destination
  field instead of the distance. GraphHopper's alternatives were too close
  to each other (29-32 km for Starnberg-Herrsching), so the candidates are
  its alternatives plus four routes over a point beside the middle.
- **Autocompletion:** Photon (OSM, komoot) from the server while typing -
  places and addresses, nearby first. Only the typed text goes out, the
  bias at ~10 km.
- **Names:** the scheme of the renaming of 2026-10-27 - "<Start> via <Place>
  <km>k <hm>hm" for loops, "<Start> to <Finish> …" from A to B. The places
  come from a local list (OSM place nodes, made by the routing container
  with each build), so the start of a route still never leaves the server.

Longest routes (Michael 2026-10-30): "Rad: 300k (egal ob one way oder
loop). Run: 100k. Da braucht es einen Hinweistext!" - by bike 300 km, on
foot 100 km, loop or A to B; the form names the limit of the chosen sport.
Long loops came out 20-24 % too long (300 asked, 360-370 km), so a second,
corrected round follows when they are off by more than 8 % (v0.15.0).

Each suggestion shows its elevation profile (Michael 2026-10-30, v0.16.0),
the three on one scale so they compare at a glance.

## Decisions (Michael 2026-10-27)

1. Edit/delete: creator + admin.
2. Tailnet only, port 1016.
3. + 4. Sports = all Garmin outdoor sub-sports of Run/Walk/Bike, stored as
   Garmin `typeKey`.
5. The next sync of each user brings deleted/changed routes into that user's
   Garmin.
6. UI English and German following the MyAuth setting.
7. `hiking` counts as Walk; `mountaineering`, `snowshoeing` and the like stay
   out.
8. Port 1016 (instead of 1012).
