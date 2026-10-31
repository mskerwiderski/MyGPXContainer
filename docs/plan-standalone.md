# Standalone and publication (plan, 2026-10-31)

Goal (Michael 2026-10-31): MyGPXContainer keeps docking onto MyAuth on
the author's server, but also runs on its own - for one person or for several - so that
it can be published. Decisions taken with the recommendations below.

## Where MyAuth was in the app (v0.17)

| Part | With MyAuth | On its own |
|---|---|---|
| Sign-in | middleware asks MyAuth for the `sso_session` cookie on every request | own accounts, sign-in/out, a session cookie |
| Who may enter, who is admin | app enabled per user, `app_admin` | a role on the account; the first account is admin |
| Garmin | MyAuth signs in (MFA) and hands out the access token | connect Garmin in the app, tokens stored encrypted |
| Sharing | the people from `/api/internal/members` | the app's own accounts |
| Profile | language, time zone, display name, header links | a profile page in the app |

## Modes: one setting `MGC_AUTH`

- `myauth` - as before; the author's instance stays on it.
- `single` - one person: the first start asks for their account (with a
  password - "no sign-in" is not offered); no sharing, no user admin.
- `local` - several people with accounts of the app's own; the admin
  invites by link, no open sign-up; sharing between these accounts.
- `none` - no sign-in at all: development and tests only.

`single` is `local` with exactly one account, without invitations and sharing.

## The layer

`app/auth/` is the one interface the rest of the app uses: `gate` (the
middleware), `is_admin`, `uid`, `account` (header), `garmin_token`, `others`
(people to share with), `sharing`. Behind it `auth/myauth.py` and
`auth/local.py`. Cross-site POSTs are refused in every mode.

## Phases

1. **v0.18 - the layer**, no new feature: MyAuth behind `app/auth/`,
   cross-site POSTs refused (CSRF - the check existed in the access block but
   was never called), tests for both. The running instance notices nothing.
2. **v0.19 - own accounts** (`local`, `single`): tables `Account` and
   `AccountSession` (done in v0.19.0), passwords hashed (scrypt), session cookie
   `HttpOnly`/`SameSite=Lax` (+`Secure` behind https), sign-in attempts
   limited, a setup page on the first start, profile (language, time zone,
   password), user admin (invite link, disable, reset password). Passkeys
   later.
3. **v0.20 - Garmin in the app** (done in v0.20.0): the MyCommons block `garmin_login` (as in
   the Garmin MCP's standalone mode): e-mail, password, MFA code; the
   password is never stored, the tokens are encrypted per user (Fernet, key
   from `MGC_SECRET_KEY` or a key file in the data dir) and renewed by the
   app.
4. **v1.0 - publication** (done: v1.0.0, a new public repository with a fresh history; the private one with the old history was deleted):
   - no host-specific things in the repo: `docker-compose.yml` with a port
     and no Caddy network, the author's settings in his infrastructure repo; the image
     does not assume MyAuth (without `MGC_AUTH` it starts in `single` with
     the setup page, never open); the home time zone a setting;
     `docs/plan.md` and `CLAUDE.md` without personal examples;
   - git history checked; if in doubt, a fresh public repo and this one
     stays private;
   - routing optional (compose profile `routing`, a small default region,
     memory figures); without it `/suggest` is off;
   - images for amd64 + arm64 from GitHub Actions to GHCR, tests and ruff in
     CI;
   - MIT licence, "unofficial, not affiliated with Garmin or Komoot"; the
     Garmin and Komoot APIs are undocumented; Photon, Open-Meteo and the tile
     servers have usage rules - named in the README and configurable;
   - README for strangers: quick start, settings, connecting Garmin, where
     the data lives, screenshots;
   - a security review before switching to public.
