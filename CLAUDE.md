# MyGPXContainer

Repo, server and Caddy conventions are portfolio-wide in
`msk-core/CONVENTIONS.md` (injected by the SessionStart hook). Only what is
specific to MyGPXContainer is here. Plan and decisions: `docs/plan.md`.
Docs and code comments are English; the UI is English and German (below).

## Principles
- **Who signs in is behind ONE layer, `app/auth/`** (v0.18.0,
  docs/plan-standalone.md): `MGC_AUTH` = `myauth` (the author's instance; unset +
  MGC_AUTH_URL means the same), `local` / `single` (own accounts, v0.19.0)
  or `none` (development, tests). Pages only use `auth.gate` (middleware),
  `is_admin`, `uid`, `account`, `garmin_token`, `others`, `sharing` - never
  a provider module. `request.state.user` is the same dict in every mode
  (uid, username, display_name, language, timezone, app_admin).
- **Own accounts (`auth/local.py`, modes `local`/`single`)**: tables
  `Account` (its id = the uid everywhere) and `AccountSession` (sha256 of the
  cookie token `mgc_session`, 30 days). First start -> `/setup` makes the
  admin, then it is gone. `local`: the admin invites on `/admin/users`
  (one-time link, 7 days; disable, admin, new link), sharing between active
  accounts; `single`: no people page, no sharing. Passwords scrypt (standard
  library, >= 10 characters); 5 failed sign-ins per address in 15 min ->
  429; the log-out link carries a value derived from the session. Language
  "" = the browser's, time zone "" = `MGC_TIMEZONE` (else `TZ`, else UTC).
  These pages answer 404 in mode `myauth`. Tests: `tests/test_accounts.py`
  (fixtures `local_mode`, `single_mode`).
- **Garmin for own accounts (`auth/garmin_link.py`, v0.20.0)**: the MyCommons
  block `garmin_login` (`app/garmin_login/` is a copy, `MyCommons/sync.sh
  garmin_login app`) - `signin` speaks Garmin's protocol, `keeper` (1.1.0,
  shared with MyAuth since v1.0.1) holds the sign-in waiting for its MFA code
  (10 min, a twin submission counts as done), seals the tokens and renews
  one at a time. Here only: `GarminLink` per uid (sealed with Fernet - key
  `MGC_SECRET_KEY`, else `secret.key` in the data dir, 0600; lose it =
  connect again) and the texts. The password is stored nowhere. Mock points
  `garmin_link._signin()` and `_renew(oauth1)`. Proven live (2026-10-31, a
  test instance in mode local): sign-in with MFA, tokens sealed in the
  table, courses and devices read with them, a forced renewal.
- **Security (review 2026-10-31, tests in test_app/test_accounts/test_sources)**:
  JSON in `<script type="application/json">` only through `web.script_json`
  (escapes `<>&` - a route name once ended the block, stored XSS);
  `SECURITY_HEADERS` in main.py with a CSP without inline scripts - so NO
  `onsubmit=`/`onclick=` in templates: `form[data-confirm]` and
  `[data-select-on-focus]` are handled in app.js; back/next paths only via
  `web.local_path` (no `//`, no backslash); bodies > MGC_MAX_BODY_MB -> 413;
  uploads parsed in a thread. First start of local/single needs the setup
  code (MGC_SETUP_CODE or `setup-code` in the data dir, logged), one setup at
  a time. Link imports: ports 80/443 only, the CONNECTED address is checked
  again (`link._connected_to_public`, DNS rebinding), no proxy from env.
- **Cross-site POSTs are refused in every mode** (`auth.cross_site`: Origin
  host != Host / X-Forwarded-Host, or `Sec-Fetch-Site: cross-site`) - apps
  behind one MyAuth share a host name, cookies don't separate ports.
- **The repo is public and generic (v1.0.0)**: nothing of the author's server
  in it - `docker-compose.yml` has a port and the routing service as profile
  `routing`; the settings of the author's instance (MGC_AUTH=myauth, MyAuth
  URL, proxy network, routing heap, TZ, no port) are in his private
  infrastructure repo
  `mygpxcontainer/docker-compose.override.yml`, deploy steps in its README
  (the sync must exclude the override). Without MGC_AUTH the app runs in
  `single`; `routing.FIRST` is empty (admins pick regions). Lint rules are
  pinned in pyproject (`ruff check app tests`); CI in `.github/workflows/`.
- **Multi-user through MyAuth** on the author's instance. **Every
  route and folder belongs to one user** (v0.11.0, Michael 2026-10-29): only
  they see and change it, `app_admin` included - someone else's id answers
  404. `app_admin` only manages the map regions of the loop suggestions
  (`auth.is_admin`, `/admin/routing`). `created_by_*` = the owner. Whoever stores a uid stores the username
  with it (a rebuilt MyAuth can reuse uids); `routes.owned_by(user)` /
  `get_own` / `folders.get_own` are the one way to a user's rows.
- **Garmin only in the user's own account**: token per request through
  MyAuth (`/api/internal/garmin/token?uid=<uid>&app=mygpxcontainer`) - never
  another user's uid, never sending or removing for someone else.
- **Sign-in and Garmin token come from the MyCommons block `access`**
  (`app/access/` is a copy - never edit it here; change it in MyCommons,
  then `MyCommons/sync.sh access app`). `app/auth/myauth.py` is the thin layer:
  `myauth.configure(app="mygpxcontainer", ...)` with MGC_AUTH_URL /
  MGC_AUTH_PUBLIC_PORT, the pages for each outcome of `access.web.check`
  `garmin_token` with its translated texts and the people to share with.
- **Garmin requests go through the MyCommons block `garmin_api`** (since
  v0.16.1; `app/garmin_api/` is a copy, `MyCommons/sync.sh garmin_api app`).
  `garmin_courses.py` keeps what is MGC's own - the course built like
  Michael's, our elevations, the delete retries, `GarminError` (text for the
  row, `status`) and the device list; `sources/garmin.py` reads through it.
  A new Garmin endpoint goes into the block, not here.
- Bump the version only in `app/version.py` (and `pyproject.toml`), commit
  message `vX.Y.Z: …`; `/healthz` reports it.

## UI: msk-ui, English + German
- msk-ui copy in `app/static/ui/` (via `sync.sh`, never edit directly);
  `app.css` only for what is the app's own, no colour values except tokens.
- **Language follows MyAuth** (`language` from `/api/session`, without a
  sign-in the browser, otherwise English; `i18n.pick`). English is source and
  key: templates `{{ _("Text") }}`, Python `N_("Text")` (translated only when
  shown), values as `{name}`. Every new text needs an entry in `i18n.DE` -
  `tests/test_i18n.py` finds missing and orphaned entries (Python via AST,
  templates via regex: the text as a literal in `_()`, no variables). Route
  names and descriptions are never translated.

## Routes and GPX
- **The stored file is the one that came, with MGC's own heights** (v1.5.0,
  Michael 2026-11-01 - until then it stayed byte-identical): `store.py`,
  content-addressed `store/ab/cd/<sha>.gpx`. The same file twice among ONE
  user's routes = duplicate, judged on the file AS IT CAME
  (`Route.original_sha`, or `gpx_sha`). Figures (`gpx.stats`) are in the
  `Route` row; map/profile are computed by `gpx.display` on request (cached
  per SHA and direction).
- **Heights from the elevation model (`elevation.py`, v1.5.0)**: every route
  that is made (upload, link, Komoot, Garmin course/activity, suggestion, a
  new file in edit) gets Copernicus GLO-30 heights through the MyCommons
  block `dem` (`app/dem/` is a copy, `MyCommons/sync.sh dem app`; shared with
  MyFITContainer): smoothed ±50 m, written into the file's `<ele>`
  (`gpx.with_elevations` - times, extensions, waypoints, prefixes stay),
  ascent/descent with a 4 m hysteresis (`gpx._climb` = `dem.terrain.gain_loss`
  - no longer the plain step sum). `elevation_source` dem | kept (no DEM
  there: the file's heights) | pending (tile not loadable: `catch_up` at
  start and every 6 h - also did the routes from before v1.5.0; one file
  for all routes sharing it). Tiles in MGC_DEM_DIR (Phoenix: /routing/dem,
  outside the backup). Creating a route can load a tile (~30 MB): async
  handlers call routes.create/update in a thread. Mock point
  `elevation._sampler()`; conftest's `NoDem` = "kept", no catch-up loop.
- **Smoothing stays ±50 m / 4 m (Michael 2026-11-01, measured live)**:
  IRONMAN Vichy bike 180 km gives 2119 m (Michael remembers 2000-2100,
  Strava ~2100); ±100 m 1839, ±150 m 1732 - too low on roads. Copernicus
  GLO-30 is a SURFACE model (tree tops): gravel loops through forest come
  out above Garmin's own course numbers (+28 % / +64 % on two of Michael's
  courses; ±150 m would give -4 % / +20 %). No single window fits both;
  the road reference wins. The real remedy for forest would be a terrain
  model without trees (e.g. Bavaria's open DGM) - not done.
- **Direction (v1.1.0, Michael 2026-10-31)**: every drawing of a route shows
  which way it goes - arrows on the Leaflet maps (`mgcArrows` in
  map_base.js, every ~110-150 px, drawn again on zoom; route page, overview,
  suggestions) and in the list sketches (`gpx.sketch` -> `arrows`,
  `clockwise`; macro `sketch_of`). "Reverse direction" only flips
  `Route.reversed` and recomputes the figures - the file stays as uploaded.
  So the track is read ONLY through `routes.track_of(route)` (drawings,
  figures) or `routes.gpx_bytes(route)` (download, Garmin: a written GPX with
  the points reversed, no times) - never `store.get` directly. A new file
  resets the direction. `garmin_sync.route_hash` adds "reversed" only when
  set (older courses keep their hash). The route page swaps its parts
  (`data-swap`), route_map.js draws map and profile again on `mgc:swapped`.
- **Way types and surfaces (v1.2.0, `waytypes.py`, Michael 2026-11-01, like
  Komoot)**: our GraphHopper matches the track (`POST /match`, profile bike or
  foot by the sports, details road_class/surface/track_type - all three are
  encoded values already; ~1 s for 60 km live). Categories in a FIXED order
  (`WAY`, `SURFACE`; "unknown" last, grey); a missing surface comes from the
  track grade. Kept per file + profile in `WayInfo` (copies and shared
  routes ask once); a turned route reads it backwards (`_for`). GraphHopper
  4xx (outside the regions) is kept and asked again after a day, 5xx/no
  answer is not kept. The route page shows it at once when known, else asks
  `?ways=1` after showing (route_map.js `askWays`); a click on a type lights
  its stretches up (fractions of the way cut from the map line), the rest
  goes grey. Colours: `--series-1..7` in app.css, both modes - the dataviz
  reference palette, validated against msk-ui's surfaces (keep the order;
  re-validate if it changes). "Gravel" is a sport label already - the
  surface is "Gravel surface" (German "Schotter"). Mock point
  `waytypes._match(body, profile)`.
- **Copy (v1.1.0)**: `routes.copy` - same owner, file, folder, sports and
  direction, name "<name> (copy)" in the user's language, deliberately no
  duplicate check; Garmin rows and "shared by" stay with the original.
- `gpx.parse` (defusedxml, elements by local name, GPX 1.0 + 1.1): all track
  segments in file order, otherwise the `rte`; (0,0) and invalid points are
  dropped (`_points_of`, the same selection `with_elevations` writes to).
- Sports = Garmin `typeKey` from `sports.py` (fetched once live,
  2026-10-27); stored in the order of `SPORTS`.
- Timestamps are UTC with tzinfo (sqlmodel ≥ 0.0.48 rejects naive ones).
- Jinja macros using `_`/`num` need `import … with context`.

## Editing the way (`drawing.py`, `draw.html`, `static/draw.js`, v1.6.0, Michael 2026-11-01)
- `/routes/{id}/draw` ("Edit the way" on the route): the browser holds the
  points as the route GOES (`routes.track_of`, so a turned route comes
  north-first) and edits them; tools re-route (section + a tapped point, or
  "without a detour"), delete (section, ends joined - Michael: "ich muss
  einen Abschnitt löschen können"), cut (start/end here), extend (end or
  start). A tap snaps to the nearest point within 30 px; tapping only, so
  it works on the phone. Undo/redo keep every state (60), Ctrl+Z/Y.
- Roads: `POST draw/leg` (2-10 points) -> our GraphHopper, the profile of
  the route's sport (`engine_of`, `suggest.ENGINE`) with `suggest.RULES`,
  no round trip; "Straight line instead of roads" draws directly (forced
  without `MGC_ROUTING_URL`). Figures: `POST draw/preview` (debounced,
  heights from the model like on save, no file written).
- Save = a NEW file from the points (`gpx.write`, no times/extensions),
  through `routes.update` (over the route: new SHA -> Garmin course
  changed, way types again, `reversed` off since the points are in the
  drawn order) or `routes.create` "<name> (copy)"; the model's heights like
  every import. Mock points `suggest._route`, `elevation._sampler`.

## Garmin activities as routes (`activities.py`, v1.4.0, Michael 2026-11-01)
- Always the signed-in user's Garmin token: own activities, someone else's
  only when public (403 -> "does not share"); without a Garmin connection the
  mode's own "connect it" text. Two ways in: an activity LINK in the link
  form (sources/garmin.py hands `/activity/<id>` to activities.fetch) and
  `/routes/garmin` (defined before /routes/{route_id}): the user's
  activities with GPS (`hasPolyline`), a page of PAGE at a time, filters
  sport (Garmin parent typeKeys) and dates passed to Garmin; a multisport
  activity shows its parts below it, each taken alone (the link of a
  multisport parent says so); taken ones are marked (source
  "garmin_activity", external_id = activity id -> duplicate check).
- Only the way: Garmin's GPX export parsed, `clean` drops points closer
  than 8 m to the last kept (standstill knots, 1-s recording), written anew
  - NO times, NO heart rate. Name by the suggestions' scheme
  (`scheme_name`, fallback the activity name without a place list),
  activity name and date in the description.
- MyCommons `garmin_api` 1.2.0: `list_activities` (paged, filtered) and
  `activity_gpx` (download-service/export/gpx/activity) - tried live
  2026-11-01. Mock: `FakeActivities` in tests/test_activities.py.

## Share links (`app/sources/`)
- `sources.fetch(url, uid)` -> `Fetched` (GPX bytes, name, description,
  suggested sport, `source`/`external_id`). The same tour/course a second time
  is a duplicate, even if it has changed since.
- **Komoot** (`komoot.py`): `api/v007/tours/<id>?share_token=…&_embedded=
  coordinates`, without sign-in. Without a valid token 403. **No Accept
  header** - Komoot answers `application/json` with 406 (live 2026-10-27).
  `gpx.write` builds the GPX from the coordinates.
- **Garmin** (`garmin.py`): always with the token of the SIGNED-IN user
  (`auth.garmin_token`); own and public courses.
- **Any URL** (`link.py`): SSRF protection - every host, also after every
  redirect, must resolve to global addresses (`_public`); the code follows
  redirects itself (at most 5), 10 MB, 20 s.
- Mock points: `komoot._get_json`, `garmin_courses._client`, `link._get`/`_public`,
  `app.access.myauth._fetch_garmin(uid)`.

## Sharing (`routes.share`, `auth.others`, `share.html`, v0.11.0)
- Sharing = a **copy** for the other user (Michael 2026-10-29): new uid, their
  default folder, `shared_by_*` + `shared_from` (uid of the original) +
  `shared_at`; the GPX is the same SHA in the store. Later changes on either
  side stay there. Someone who has it already (same SHA, same source +
  external_id, or a copy of this route) gets none - "already there".
- Who can be picked comes ONLY from MyAuth: `GET /api/internal/members?uid=
  &app=` (app key, MyAuth ≥ 0.57.0, APPS flag `"members": true`), via
  `myauth.call`, cached 60 s per uid; the form's `to` uids are checked against
  it. Mock point `auth.myauth._fetch_members(uid)`. Without sharing in the
  mode (`auth.sharing()` False) the share buttons are hidden.
- `GET /routes/share?ids=…&back=<local path>` (from the route and from the
  selection bar, action `share`), `POST /routes/share` renders the page again
  with the result (`data-swap="share-panel"`). Defined before
  `/routes/{route_id}`.
- List filter "From" (`by`): "me" = not shared, otherwise the username of
  who shared it; shown only once something was shared.
- Migration v0.11.0 (`db._split_by_owner`, once, when `shared_from` is
  missing): whoever had someone else's route marked for Garmin got a copy and
  their `GarminCourse` row points to it; routes in someone else's folder went
  to a same-named folder of their owner.

## Route suggestions (`suggest.py`, `places.py`, `routing.py`, `routing/`, v0.12.0)
- `/suggest`: start (browser location or a place), sport, km, profile ->
  three round trips from OUR GraphHopper (positions stay on the server). 12
  headings in parallel (`round_trip`, heading gives the variety, the seed
  hardly), custom model per request = `WISH[profile]` + `RULES[engine]`;
  score = distance, profile, run-twice share, big roads, unpaved (gravel +,
  road bike -); `pick` keeps three ≥ 60° apart with < 40 % shared ground.
  Weights from the trial run 2026-10-30 (docs/plan.md). "Take over"
  (`POST /suggest/take`) computes the loop AGAIN from the parameters - no
  state, source `generated`. Mock point `suggest._route(body)`, `FakeGH` in
  `tests/test_suggest.py`.
- Longest route (Michael 2026-10-30, `suggest.LIMIT_KM`): by bike 300 km, on
  foot (run and walk) 100 km - for loops the wished distance, from A to B
  the route itself (the crow distance only as a first check; longer
  candidates are left out). The form says it ("Routes up to … km") and
  follows the sport. GraphHopper's loops grow too long on long distances
  (300 km asked: 360-370): off by > 8 % -> a second round with the distance
  corrected; the card keeps the distance actually asked (`asked_km`), which
  take-over asks again.
- **Stops on the way (v1.3.0, Michael 2026-11-01)**: any number
  (`STOPS_MAX` 50 only against abuse), in the order given, reordered by
  dragging the handle (pointer events - phones do no HTML5 drag) or the
  arrow keys on it; from 5 on the list folds to first and last. Each stop
  is ONE hidden field `via` = "lat,lon,label" (app.js drops empty fields, so
  three parallel lists would lose their alignment); lat/lon empty = typed,
  not picked -> looked up like the start. "Choose on the map" (v1.3.2,
  right under loop / A to B): ONE map for start, stops and destination; the
  switch "A tap sets ▶ Start | Stop | ⚑ Destination" moves on by itself
  (start -> destination -> stops, `nextMode`); a tapped point is named by
  `/suggest/where` (local place list). The map sits above the fields, so it
  does not move while the stop list grows. Each stop: ⋯ menu "Use as start
  / destination" - they SWAP (the old start/destination takes the stop's
  place; "My location" becomes a stop of that name), × removes directly.
  The pick radios have `form="pick-none"` (never sent).
  A to B: through the stops ("s") or over a point beside the longest leg
  ("w<n>"); no GraphHopper alternatives (they take two points only).
  Loops: start -> stops -> start, a shaping point per leg pushed outward
  (one stop: both legs to their right = opposite sides) - from width 0.6 on
  three along a bow (one far point gave out-and-back spurs: 60 km over one
  near stop ran 19-30 % twice, with the bow 0-14 %, live); its width from the
  wished km (`loop_width`, DETOUR 1.3), candidates vary width and position
  ("L<m|q>:<width>" - take over recomputes it), a second round when off by
  more than 8 %. Too short a wish for the stops -> a note with the least.
  Names: "Starnberg via Percha, Andechs …" (`places.route_head(…, stops)`).
- Each card has an elevation profile (v0.16.0, `pages._profiles`, inline
  SVG): all three on ONE scale (same km, same metres; at least 60 m range so
  flat stays flat), in the card's colour like its line and sketch
  (`.loop-c0..2`). `profiles` in the page context is taken (the profile
  names) - the paths are `elevations`.
- From A to B (v0.14.0): GraphHopper's `alternative_route` stays close
  together, so candidates = its alternatives ("a0".."a2") + four routes over
  a point beside the middle (`suggest.via`, ±15/30 % of the distance,
  "v0".."v3"); score on the length beyond the shortest; `pick(apart=False,
  shared=0.6)`. Take over recomputes by key (`oneway_one`).
- Names on take over: Michael's scheme of 2026-10-27, the same in every
  language - "Starnberg via Percha 42k 380hm" (via = locality of the point
  farthest from the start; in the start's own town its suburb), "München to
  Schliersee 118k 1240hm"; rides whole km, runs/walks one decimal with a
  point. Places from the routing container's `places.json` (OSM place nodes
  city/town/village/suburb, `osmium tags-filter` + `export`) - LOCAL, the
  start never leaves the server; a city counts 4×, a town 2× as far
  (`places.locality`). Without the list: the town of the picked label.
- Address search while typing (`GET /suggest/places`, `places.search`):
  Photon (`MGC_PHOTON_URL`, photon.komoot.io) from the server, the bias
  (form start, else the median start of the user's routes) rounded to 0.1°.
  Tests never reach it: `places._get_json` is blocked in conftest.
- The form (`form.card.stack`): msk-ui's `form.card label` puts .9rem BELOW
  a label meant to wrap its field; with label and field side by side that
  gap lands between them. So each entry is a `.field` (label + control,
  .35rem), the groups apart by the stack gap (Michael 2026-10-30).
- `search._num` rejects negative numbers - never use it for coordinates
  (London is west of Greenwich): `pages._coord`/`_point`.
- Profile limits per sport (Michael 2026-10-30): bike 7/15 hm per km, on
  foot 20/50 - `sports.profile(distance, ascent, sport_keys)`, a route is on
  foot only without any bike sport; also the list tags and filter.
- Routing container `mygpxcontainer-routing` (`routing/`, GraphHopper 11.1,
  flexible mode only): `run.py` (standard library) builds from
  `regions.json` and answers with `status.json`, both in the volume shared
  with MGC (`MGC_ROUTING_DIR=/routing`). Build = download (md5) -> `osmium
  merge` -> `import` (low CPU priority, graph in MMAP files instead of the
  heap) into a new graph dir while the old one serves -> switch -> extracts
  deleted; due when the regions or the rebuild token change, or after 30
  days (then only between 1 and 5 at night); a failed wish waits 6 h. Each
  build also writes `places.json`; a graph without one gets it by a
  places-only run (download + osmium, no import; a container restart tries
  it at once). Downloads try 3× on 5xx/429/broken connections (Geofabrik
  answered 502 live, 2026-10-30). Tests load `routing/run.py` by path.
- A COLD GraphHopper answered MGC's twelve parallel requests in 30 s instead
  of 1 (twice live, 2026-10-30): the server now starts with its whole heap
  (`-Xms` = `-Xmx`) and `warm_up()` runs a few round trips from cities of
  `places.json` right after every start; MGC sends at most
  `suggest.PARALLEL` (6) requests at once (a semaphore per event loop - the
  tests run one loop per call).
- Measured 2026-10-30, Germany: download 2 min, import 37 min, graph 2.7 GB,
  serving 3.4 GB RAM; an import in the Java heap peaked at ~18 GB (hence
  MMAP); disk 7.5 GB with the extract, ~3 GB without.
- Pitfalls (found live 2026-10-30): Geofabrik redirects big extracts
  (Germany) to a mirror and has the `.md5` only there - resolve the redirect
  first. `ADD --chmod` also sets the created parent dir -> `mkdir -m 755
  /app` before it. GraphHopper refuses a custom model named like a built-in
  one (`bike.json` …) in `custom_models.directory`; `sac_scale` is no encoded
  value in 11.1.
- Regions (`routing.py`, table `RoutingRegion`): app admins on
  `/admin/routing`, search in Geofabrik's index (`index-v1-nogeom.json`, mock
  point `routing._get_index`); a region inside one on the list is refused,
  regions inside a new one leave it. First start: Germany and Greater London
  (`routing.FIRST`) - only if neither rows nor `regions.json` exist
  (removing all stays removed).
- The routing volume is rebuildable: no need to back it up.

## Garmin (`garmin_sync.py`, `garmin_courses.py`, v0.17.0)
- **Nothing happens on its own** (Michael 2026-10-31, "nicht einleuchtend für
  den normalen User"): no marks, no sync. The user SENDS routes on request
  and REMOVES courses on "My Garmin". The UI never says "sync"; the verbs are
  "send" and "remove", the places "Garmin Connect" and the device's name.
- "Send to Garmin…" (route page, and action `garmin` in the list's
  selection bar) -> `GET /garmin/send?ids=…&back=` (like sharing): every
  route with a sport picker (its first sport preselected, or the one already
  in Garmin; a route without sports picks from all), Garmin Connect always,
  devices ticked on top (one, several or "All devices", only the user's OWN
  list, otherwise 422). `POST /garmin/send` queues job `("send", items,
  devices)` and renders the page again; it polls via `data-refresh-url`
  (`…&sent=1`, the result of the last run).
- `GarminCourse` = a course that IS in the user's Garmin Connect (uid +
  username, `name` when sent, deliberately no FK). Sending again: unchanged
  (`synced_hash`, which includes the sport) -> the course stays; changed or
  another sport -> delete + create, the devices that had the old course move
  to `pushed_old` ("(old version)"). Deleting a route leaves its course
  (state "Route deleted" on My Garmin). A changed route shows "Changed" and
  waits for the user to send it again.
- "My Garmin" (`GET /garmin`) comes AT ONCE with what the DB knows and
  "Checking Garmin Connect…" (Michael 2026-10-31: the user must see that
  something happens); `garmin.js` then fetches `/garmin?fresh=1` and swaps the
  panel. Only `fresh=1` calls `garmin_sync.refresh` (while no job runs) -
  one `owned()` call: rows whose course is gone in
  Garmin drop out (never made again), missing names are filled from Garmin,
  the device list is renewed. Checkboxes + "Remove selected" / "Remove all"
  (`POST /garmin/remove`, job `("remove", ids)`, foreign row ids ignored),
  `garmin.js` asks first. Both pages carry the hint that devices only go one
  way (Garmin can neither update nor delete a course on a device).
- Only what Garmin still has AND what carries our mark `MGC:route=<uid>` in
  its description is deleted - any route uid (since v0.11.0 a row may point
  to the user's copy while the course carries the original's uid). The list
  (`course/owner/<displayName>`) has NO description (live: null) - the mark
  is only in `GET course/<id>`. A course without the mark is left in Garmin
  and its row dropped, with a note. Only the user's OWN routes can be sent
  (`garmin_sync.route_of`).
- Migration v0.17.0 (`db._rows_are_courses`, once, while `wanted` exists):
  rows without a course go, unmarked rows whose course still exists stay
  (the user removes them), `name` from the route, `wanted` dropped.
- Right after creating, Garmin's DELETE answers 429 "not yet ready to delete
  or update" (live 2026-10-27); `delete` tries 5× every 5 s, then an error on
  the row (shown on My Garmin) and the row stays.
- Garmin's import returns the geoPoints WITHOUT elevation; `_fill_elevation`
  interpolates our elevations over the distance. Fields like Michael's own
  courses: private (`rulePK` 2), `elevationSource` 3, WGS84.
- Background: `garmin_sync.start_send` / `start_remove` (asyncio task, one
  run per user, jobs queue up; `Run.result` = outcome of the last job) - the
  endpoints that start it must be `async def` (there is no event loop in the
  thread pool).
- Devices: a device message (`device-service/devicemessage/messages`,
  messageUrl `course-service/course/fit/<course>/<device>?elevation=true`,
  like "Send to device" in GC) after the course is in Garmin Connect.
  `pushed_to` = devices of the CURRENT course. **Devices differ per user**
  (Michael 2026-10-27): `GarminPrefs.devices` per uid + username, only
  `courseCapable`, always fetched with the signed-in user's token. The send
  page loads the list while none is known (without a result at most every
  10 min again), My Garmin renews it. Proven live: device list, FIT per
  device (Edge 850, fenix 8 Pro) and the whole "send to device" - the route
  arrived on the Edge (2026-10-31).
- No `pgrep -f`/`pkill -f` in the same Bash call as `git commit`/`push`: the
  protection hook reads the `-f` as a force push and blocks the whole command.
- Mock point `garmin_courses._client(token)` (the block's client), in tests
  `fake_client(handler)` with `FakeGarmin.request(token, request)` from
  `conftest.py` (one account per token, `.devices`, `.messages`): real HTTP
  requests through httpx's MockTransport, nothing leaves.

## Folders and multi-select (v0.8.0)
- Folders belong to one user like the routes (v0.11.0); every route is in
  exactly one of its owner's. Default folder "General/Allgemein" = NO row,
  `Route.folder_id` None. Deleting a folder moves its routes there. A foreign
  folder id in a form = the default folder (`folders.valid_id`). Columns are
  added via `db._migrate` (create_all adds no columns).
- Selection mode of the list (`body.selecting`, `routes_list.js`): checkboxes
  with `form="bulk-form"`, a bar with "Send to Garmin…", move, share and
  delete -> `POST /routes/bulk`, redirect to the list with `done/n`
  (garmin/share: on to `/garmin/send` / `/routes/share`). Delete (v0.13.0)
  asks first in `routes_list.js` - its submit listener runs before app.js's,
  which sends nothing once the event is prevented; Garmin courses stay.
- **A field `name="action"` shadows `form.action`** - so app.js reads
  `getAttribute("action")`. The bug sent bulk POSTs to
  `/[object RadioNodeList]`.

## No full reloads (`static/app.js`, Michael 2026-10-27)
- A click never reloads the whole page and never jumps. Pattern:
  `form[data-swap="id1,id2"]` goes out via fetch, the server answers as
  always (redirect to a rendered page), only these ids are swapped. If the
  server redirects to a DIFFERENT page, the browser follows normally. No JSON
  twin of the routes; without JS it stays a normal form.
- `form[data-auto]` (filters) submits itself on every change, text after a
  pause, and writes its state into the URL - without empty fields and
  without values equal to their `data-default`.
- `[data-sync-running]` + `data-refresh="ids"`: polls `/garmin/status` and
  swaps the ids when the Garmin job is done - from `data-refresh-url` if set
  (a page answered to a POST), else from this page.
- New buttons/forms get `data-swap` and an id on the target area.
- Swipe to delete (phone, `swipe.js`): rows with `data-swipe-delete` (since
  v0.11.0 every row - the list holds only the user's own). After a swipe the browser often sends NO click - a
  "swallow the next click" guard must therefore be time-limited, otherwise it
  eats the tap on "Delete".
- Every subpage has `a.back[data-back="/path"]` at the top: if you came from
  exactly this page, it goes back via `history.back()` (filters and scroll
  stay), otherwise via the href - as a home-screen app there is no browser
  back button.
- `mgc.toast` needs the class `show` (msk-ui does not fade it in otherwise).
- List: filters in Python (`search.py`), place via Open-Meteo geocoding
  (`geocode.py`, mock point `_get_json`, autouse without network in tests),
  "Near me" via the browser's geolocation.
- Browser test locally: Playwright in a scratch venv with
  `executable_path="/usr/bin/chromium"`; start the app with patched mock
  points (`app.access.myauth._fetch_session`, `_fetch_garmin`,
  `garmin_courses._client` = `fake_client(FakeGarmin().request)` from the tests).

## Tests
- No test talks to MyAuth: mock point `app.access.myauth._fetch_session(cookie)`, fixture
  `myauth` (`.status`, `.body`, `.calls`); the share list `auth.myauth._fetch_members(uid)`,
  fixture `people` in `tests/test_sharing.py`. Settings are cached - fixtures
  that set env variables reset `config._settings = None`.
