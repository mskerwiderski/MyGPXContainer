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
  garmin_login app`) signs in on the account page (e-mail, password, MFA
  code; a sign-in waiting for its code lives in `_pending` for 5 min). The
  password is stored nowhere; OAuth1/OAuth2 in `GarminLink` per uid,
  encrypted with Fernet - key `MGC_SECRET_KEY`, else `secret.key` in the data
  dir (0600, made on first use; lose it = connect again). `token(uid)`
  renews the OAuth2 token when due, one at a time per uid. Mock points
  `garmin_link._signin()` and `_renew(oauth1)`.
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
- **The uploaded file stays byte-identical** (`store.py`, content-addressed
  `store/ab/cd/<sha>.gpx`); the same file twice among ONE user's routes =
  duplicate (two users may have it, the store keeps it once). Figures
  (`gpx.stats`) are in the `Route` row; map/profile are computed by
  `gpx.display` on request (cached per SHA).
- `gpx.parse` (defusedxml, elements by local name, GPX 1.0 + 1.1): all track
  segments in file order, otherwise the `rte`; (0,0) and invalid points are
  dropped. Ascent = sum of the elevation steps like Komoot/Garmin,
  deliberately without smoothing.
- Sports = Garmin `typeKey` from `sports.py` (fetched once live,
  2026-10-27); stored in the order of `SPORTS`.
- Timestamps are UTC with tzinfo (sqlmodel ≥ 0.0.48 rejects naive ones).
- Jinja macros using `_`/`num` need `import … with context`.

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
  10 min again), My Garmin renews it. Proven live: device list and FIT per
  device (Edge 850, fenix 8 Pro); the POST of the message had not run live
  yet at v0.9.1.
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
