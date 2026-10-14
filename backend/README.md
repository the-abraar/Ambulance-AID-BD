# Backend (MVP wedge)

Mission state machine + FastAPI dispatch API. No signal preemption (see `docs/architecture/future-integrations.md`).
Not deployed. SQLite for dev; Postgres supported. API contract: `docs/api-spec/openapi.yaml` (a test fails if a route
is missing from it).

    python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
    .venv/bin/pytest
    export AMBULANCE_DEV=1                                 # dev only: allows dev.db and serves /docs
    .venv/bin/python -m app.bootstrap admin alice          # prints user_id + token once; only sha256 stored
    .venv/bin/python -m app.bootstrap dispatcher carol     # dispatch only
    .venv/bin/python -m app.bootstrap driver bob           # prints driver_id + token
    .venv/bin/python -m app.bootstrap vehicle "Op" DHK-1   # prints vehicle_id
    .venv/bin/python -m app.bootstrap revoke USER_ID       # kill any user's token at once
    .venv/bin/python -m app

Production installs `requirements.lock` (pinned, hashed): `pip install --require-hashes -r requirements.lock`.
After changing `requirements.txt`, regenerate it with the command in the lock file's header (uv).

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `AMBULANCE_DB_PATH` | required | SQLite file path or `postgresql://` URL. Startup fails without it unless `AMBULANCE_DEV=1`. |
| `AMBULANCE_DEV` | unset | `1` = dev: falls back to `dev.db`, serves `/docs` and `/openapi.json`. Never set it in production. |
| `AMBULANCE_PING_RETENTION_DAYS` | `90` | GPS pings older than this are deleted at startup and once a day. Minimum 1. |
| `AMBULANCE_SMS_API_KEY`, `AMBULANCE_SMS_SENDER_ID` | unset | Both set = SMS fallback on (below). Either missing = off. |
| `AMBULANCE_SMS_URL` | `https://bulksmsbd.net/api/smsapi` | Gateway endpoint; tests point it at a local fake. |
| `AMBULANCE_ANDROID_CERT_SHA256` | unset | The Android app's signing-key SHA-256 fingerprints (`AB:CD:...`, comma-separated). Set = `/.well-known/assetlinks.json` lets the app open the console's pairing QR (App Link); unset = 404 and the QR opens the browser. A malformed value stops startup. |
| `FORWARDED_ALLOW_IPS` | uvicorn: `127.0.0.1` | Behind Caddy, set it to Caddy's address so `POST /pair`'s per-client limit sees the phone's IP, not Caddy's. |

`GET /healthz` (no auth) answers `{"ok": true}` when the DB is reachable and 503 otherwise. On Postgres a dead DB
answers only after the pool's 30 s connection timeout.

## Roles

- **driver**: status moves, pings and `POST /missions/{id}/ack`, only for the mission assigned to them; on shift,
  also pings for the paired vehicle between missions.
- **dispatcher**: creates, lists and cancels missions; pairs drivers with vehicles; may make a driver's forward move
  for them (dead phone) with a required `reason` and optional `event_time`; the audit row then holds the dispatcher as
  `user_id` and the driver as `on_behalf_of`. Back-fills paper-log missions after an outage: `POST /missions` with
  `dispatched_at` and `steps` writes the mission already over (no busy check, no SMS, no app alarm).
- **admin** = a dispatcher with `users.admin` set: also creates users, mints, rotates and revokes tokens, and issues
  pairing codes. `GET /me` returns `admin`.

**Migration 0006 makes every existing dispatcher an admin**, so nobody loses access on upgrade. To get the split, have
an admin create dispatch-only accounts (`POST /users` or `python -m app.bootstrap dispatcher NAME`), hand those to the
dispatch desk, and keep admin tokens off shared PCs. If an admin token is stolen, on the server run
`python -m app.bootstrap revoke USER_ID` and `python -m app.bootstrap admin NAME`.

## Rules worth knowing

- Tokens: 256-bit random, stored as SHA-256, expire 90 days after last use (sliding; written at most once a day).
- Pairing: `POST /drivers/{id}/pairing-code` (admin) gives a 6-digit code, single use, 10 minutes, stored hashed. The
  driver app sends it to `POST /pair` (no auth) and gets `{token, user}`; the old token stops working. Wrong codes never
  kill anyone's code: one client (IP address) gets 20 wrong codes per 10 minutes, and a success clears its count, so an
  office pairing 15 drivers survives their typos; all clients together get 50 per 10 minutes, so at most 50 guesses
  fall in a code's life (1 in 20,000). Past that, `/pair` answers 429 to everyone until the window passes and logs a
  warning; an attacker can pause pairing this way but not take over a code (fallback: the admin's "Show token").
  Revoke kills live codes.
- One active mission per vehicle and per driver (409), enforced by partial unique indexes as well as the check.
  A mission with a driver needs a vehicle: give a vehicle alone (its paired driver is used) or a driver alone (his
  paired vehicle is used).
- Missions list newest first; `?active=true` returns every non-terminal mission unpaged. Missions carry `created_at`,
  `acknowledged_at` and `<status>_at` per status. `/missions/current` also returns a mission that ended in the last
  10 minutes, so the driver sees "cancelled" instead of a blank screen.
- Pings: the phone clock may be wrong. The server stores its receive time (minus the fix's age when `sent_at` is sent)
  and returns `clock_skew_s`. It rejects (0, 0), fixes older than 300 s, and jumps faster than 250 km/h beyond 1 km
  plus the reported `accuracy`. 1 ping/s per vehicle (DB-backed, holds across workers).
- Pings between missions (free vehicles on the map): only with `on_shift: true` (the Android wrapper's shift mode),
  only from the driver paired with the vehicle, only while the vehicle is in service and neither it nor he is on
  another mission. The server keeps one position per 30 s and answers the rest 201 with `stored: false`. Unpaired,
  off shift or signed out: nothing is kept. `GET /me` gives a driver `paired_vehicle_id`.
- Creates (missions, drivers, users): 30 per minute per token.
- Driver phone: `01XXXXXXXXX`, `8801...`, `+8801...`, Bangla digits, spaces and hyphens accepted; stored as
  `+8801XXXXXXXXX`; anything else is 422.
- Validation errors (422) never echo the request body back.
- Schema: Alembic (`migrations/`), applied at startup in dev and tests. Under compose, the one-shot `migrate` service applies them as the owner role (`ops/migrate.py`); the app's `ambulance_app` role cannot change the schema. Postgres/PostGIS swap: change TEXT ids/timestamps to
  uuid/timestamptz, add geography(Point).

## SMS fallback

On mission create and on cancel, if the driver has a phone and both SMS variables are set, the server sends one short
text (mission id, address, Google Maps link) through the [BulkSMSBD](https://bulksmsbd.net) HTTP API
(`POST api/smsapi` with `api_key`, `senderid`, `number`, `type`, `message`). It runs after the HTTP response, so it never
delays or fails dispatch. Every attempt, sent or failed, is a row in `sms_audit` (mission, driver, event, result; no
phone number, no key).

**TODO (owner):**
1. Open a BulkSMSBD account, top up a balance, and get an API key and an approved sender ID (a masking/brand sender ID
   usually needs BTRC approval, which the gateway arranges; ask them, a non-masking number may do for a pilot).
2. Put the key and sender ID in the server's environment (never in git).
3. UNVERIFIED until step 1: that `response_code` 202 means accepted, and that `type=unicode` delivers Bangla
   addresses correctly. Send one English and one Bangla test mission to your own phone before relying on it.

## Doc conflicts (and the choice made)
1. `dispatch-and-citizen-platform.md` diagram models the *vehicle* cycle (AVAILABLE, DECONTAMINATION, no COMPLETED/CANCELLED); `openapi.yaml` MissionStatusUpdate has COMPLETED/CANCELLED and no AVAILABLE/DECONTAMINATION. Chose the OpenAPI enum as mission states; AVAILABLE/DECONTAMINATION are vehicle states, not built.
2. `security-and-anti-abuse.md` uses `DISPATCHED_TO_PATIENT`/`PATIENT_ONBOARD`, which exist nowhere else. Ignored (preemption-only, out of scope).
3. No doc defines where CANCELLED is allowed or the initial state. Chose: new mission starts DISPATCHED (create = dispatch); CANCELLED from DISPATCHED, EN_ROUTE_PICKUP, AT_SCENE only; AT_HOSPITAL -> COMPLETED (diagram's AT_HOSPITAL -> DECONTAMINATION replaced).
4. `docs/api-spec/openapi.yaml` describes only the implemented API; the preemption, telemetry and public-availability interfaces it used to list are prose in `docs/architecture/future-integrations.md`.

## Remaining
PostGIS, hospital check-in role, tenant/operator separation (one database per fleet today), idempotency keys on
queued driver writes, append-only audit role on Postgres.

## Browser e2e
`tests/e2e_browser.py` (not collected by pytest) drives /console and /driver in Chromium against a real uvicorn + fresh SQLite DB:
`python -m venv .e2e && .e2e/bin/pip install -r requirements.txt playwright && .e2e/bin/playwright install chromium && .e2e/bin/python tests/e2e_browser.py [screenshot_dir]`
