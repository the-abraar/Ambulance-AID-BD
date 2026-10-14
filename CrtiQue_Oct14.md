# Ambulance-AID-BD: independent critique (2026-10-14)

Reviewer: senior engineer / product / go-to-market, independent of `judge.md`.
Basis: I read every file in `backend/app`, `backend/web`, `backend/tests`, `backend/migrations`, the deploy files, `docs/`, `pitch/1.html`, `judge.md` and the scorecard. I ran `scripts/check.sh` (all 7 steps pass: 109 passed, 1 skipped) with a scratch venv. I started the server on a scratch SQLite DB and probed it with scripted requests. I took viewport screenshots (375x812, 1280x800) in headless Chromium. I checked GitHub CI with `gh run list` (read-only). I did a short web search on the Bangladesh market and law. Nothing in the repo was changed except this file.

Labels: **Confirmed** = I reproduced it or traced the code path end to end. **Suspected** = plausible and partly traced, not proven.

---

## 1. Verdict up front

- **What it is:** a small, clean FastAPI + Postgres dispatch backend with a 7-state mission machine, a plain-JS dispatcher console and a Bangla-first driver PWA. About 700 lines of app code, well tested at the API level.
- **Who it is for:** one ambulance fleet (under 20 vehicles) with one dispatcher. No such fleet has been named or contacted ("Count so far: 0" interviews, `docs/roadmap.md`).
- **Worth continuing?** Yes, but only as a pilot-driven tool, and only if the owner takes on the field work. Stop adding backend hardening. The next 20 hours of code must go to the dispatch loop, which breaks under normal use (see bugs B1-B4).
- **Owner intent mismatch:** `now.md` says the primary goal is automatic traffic-light control and AI cameras. That is a different product, gated on government bodies, and years away. The owner must decide which project this is. If the honest answer is "traffic lights", this repo is a detour.
- **My GTM readiness: 12%** (scorecard: 18%).

**Why 12, not 18.** The scorecard's 18% cap reasons are correct (no operator, no real phone, no host, no human review), but its dimension scores assume the core loop works. It works only in a headless browser with fake GPS and a short history. In a real pilot it fails within days: after 200 missions the console stops showing new ones (B1, reproduced). The same ambulance can be dispatched twice, and the older mission vanishes from the driver's screen (B2, reproduced). Once a patient is on board, nobody but the driver's phone can close the mission (B3, reproduced). A phone with a wrong clock sends no positions and shows no error (B4, reproduced on the server). The driver app almost certainly stops sending GPS when the driver taps its own "Navigate" button (Suspected, platform behaviour). The dispatcher must type raw latitude and longitude to create a mission. So the pilot's own success test, "faster or equal to phone/radio" (`docs/pilot-plan.md:21`), would fail today. Safety-critical software that is known to fail its own pilot test, with zero users, earns a lower cap.

---

## 2. Code and architecture

**Structure.** Fits the size. One FastAPI factory (`backend/app/main.py`, 339 lines), one DB shim (`db.py`), a pure state machine (`state_machine.py`, 44 lines), Alembic migrations, and two static front ends with no build step. This is the right amount of machinery for one fleet. No ORM, no framework on the front end, no queue. Good.

**What is genuinely good**
- One authorization rule: `required_role()` at `state_machine.py:42-44`, used by both PATCH and `/meta/transitions` (`main.py:173`, `main.py:246`). No second role check drifts.
- Compare-and-set on every status write with the audit row in the same transaction (`main.py:231-240`). The 8-thread race test passes (`tests/test_tokens.py:43-50`).
- DB-backed ping rate limit that works across workers (`main.py:274-281`), tested with 4 app instances.
- 256-bit random tokens, stored as SHA-256, with expiry and revoke (`main.py:59-67`, `db.py:112-114`).
- Front ends write dynamic text through `textContent` or `esc()`, with a lint (`scripts/lint-innerhtml.sh`) that fails on unescaped HTML sinks.
- Migrations take a Postgres advisory lock so several workers can start at once (`db.py:29-33`).
- CI runs the full check plus pytest on Postgres 16 and is green on the last 5 pushes, including `f2d3456`.

**Problems**

| # | Issue | Where | Note |
|---|---|---|---|
| A1 | Everything lives inside `create_app()`: models, helpers, routes, closures. | `main.py:26-339` | Fine at 339 lines. It makes unit-testing helpers awkward (tests reach in via `app.state.advance`, `main.py:242`). Do not split yet; split when a second file is needed. |
| A2 | Helpers commit on their own, so callers cannot make "create + audit" atomic. | `bootstrap.py:22`, `bootstrap.py:29`, used by `main.py:197`, `main.py:213` | See B10. |
| A3 | Timestamps and IDs are TEXT on Postgres too. | `migrations/versions/0001_initial.py:10` | Works because every writer uses the same ISO format. A future writer that uses `Z` or no microseconds will break string comparison of `token_expires_at` (`main.py:63`). Move to `timestamptz` before more writers exist. |
| A4 | `?`-to-`%s` placeholder rewrite by string replace. | `db.py:66` | Safe today (no literal `?` or `%` in SQL). Fragile; note it in a comment or use `%s` everywhere. |
| A5 | Dead feature: `vehicles.active` is read and checked but nothing can ever set it to false. | `main.py:110`, `main.py:190`; no endpoint | Either add "deactivate vehicle" or drop the check. |
| A6 | Dead field: `StatusIn.notes` is accepted and thrown away. | `main.py:86`, `main.py:231-240` | See B7. |
| A7 | The OpenAPI file still describes a different product: "Traffic Preemption Platform", `.gov.bd` "Production National Gateway", `/telemetry/ingest` with "MutualTLS", `/preemption/trigger`, `/preemption/release`, public `/ambulances/available`. | `docs/api-spec/openapi.yaml:4-6`, `:12-17`, `:21`, `:259`, `:286`, `:307` | `judge.md` Update 8 item 9 says the spec was rewritten to MVP shapes. It was only partly rewritten. `test_spec.py` validates responses, not that every spec path exists. |
| A8 | Unpinned dependencies; test tools in the production image. | `backend/requirements.txt:1-9`, `backend/Dockerfile:5` | `pytest` and `httpx` are in `requirements.txt` (contradicts `AGENTS.md`, "Test deps are in requirements-dev.txt"). Nothing is pinned. Today's install already prints a Starlette deprecation warning. Two builds a week apart can differ. |
| A9 | Driver/vehicle pairing is per mission, chosen in two separate dropdowns. | `web/dispatcher/index.html:25-26`, `main.py:73-74` | No shift or "driver is in vehicle X" concept. A dispatcher can pair Driver A with Vehicle B while A sits in Vehicle C, and pings then land on B's record. This is a data-model gap, not just UI. |
| A10 | No tenant concept. `vehicles.operator` is a free-text label. Every dispatcher sees and manages every vehicle and driver. | `main.py:183-216` | Violates `CODING_STANDARDS.md` ("an operator against its own vehicles"). Fine for one fleet if you run one database per operator. Say so. |

**Standards adherence** (`CODING_STANDARDS.md`)

| Rule | Status |
|---|---|
| Authorize only via `required_role()` | Kept. |
| Compare-and-set every state write | Kept for status. Mission create has no "vehicle is free" check (B2). |
| State the auth decision on every endpoint | Kept. Static mounts and FastAPI `/docs`/`/openapi.json` are open without a comment. |
| Fail closed on secrets/defaults | **Broken:** a missing `AMBULANCE_DB_PATH` silently falls back to `dev.db` (`main.py:28`, `bootstrap.py:34`). Compose accepts the placeholder `POSTGRES_PASSWORD` from `.env.example`. |
| Compare owners, not ids | Partly. The driver check is by owner. There is no operator check (A10). |
| Idempotency keys from the caller | **Not implemented anywhere.** No key on pings or status. The rule describes a feature that does not exist. |
| Cap unbounded input | Missions list capped. `/vehicles`, `/drivers` and the audit list are unbounded; fine at this size. |
| Mark unmeasured claims UNVERIFIED | Mostly kept in docs; not in the pitch (section 12). |

---

## 3. Bugs, ranked by severity

| ID | Sev | Status | Bug |
|---|---|---|---|
| B1 | Critical | Confirmed (reproduced) | Console stops showing new missions after 200 |
| B2 | High | Confirmed (reproduced) | Same ambulance and driver can be dispatched twice; older mission vanishes for the driver |
| B3 | High | Confirmed (reproduced) | No dispatcher override after AT_SCENE; a dead phone strands the mission forever |
| B4 | High | Confirmed (server reproduced, client traced) | Phone clock off by more than 60 s ahead or 5 min behind = no tracking, no error |
| B5 | High | Confirmed (traced) | One mis-click cancels a live emergency, irreversibly |
| B6 | High (security) | Confirmed (traced + probe) | Dispatcher tokens cannot be revoked; a thief can lock out the real dispatcher |
| B7 | Medium | Confirmed (reproduced) | Mission with a driver but no vehicle: driver app pings `/vehicles/null`, silently 403 |
| B8 | Medium | Confirmed (traced) | All drivers onboarded on one day expire in the same minute |
| B9 | Medium | Suspected (traced) | Offline queue can replay old pings onto a new vehicle |
| B10 | Medium | Confirmed (traced) | Missing DB env var silently uses an ephemeral SQLite file |
| B11 | Low | Confirmed (reproduced) | `notes` accepted and discarded |
| B12 | Low | Confirmed (traced) | Vehicle/driver created and committed before the audit row |
| B13 | Low | Confirmed (reproduced) | NaN in an authenticated JSON body returns 500 |
| B14 | Low | Confirmed (reproduced) | Revoked drivers can still be assigned; console cannot see who is revoked |
| B15 | Low | Confirmed (traced) | Mission cancelled: driver screen silently flips to "No mission" |

**B1. Console stops showing new missions after 200.**
- Where: `backend/app/main.py:125` (default `limit=200`), `main.py:129` (`ORDER BY created_at, id`, oldest first), `backend/web/dispatcher/app.js:88` (no `limit`/`offset`, no "active only").
- Scenario: I created 206 missions and then one more. The newest was absent from both the "All" view and the "DISPATCHED" filter. A 20-vehicle fleet doing 5 missions per vehicle per day hits this on day 2. The dispatcher creates a mission, sees nothing, and creates it again (B2 makes that worse).
- The test locks the bug in: `tests/test_api.py:167-171` asserts ascending order.
- Fix (1-2 h): `ORDER BY created_at DESC`. Make the console's default view "non-terminal missions" (no limit needed: there are never 200 active), with history as a separate paged view. Change the test.

**B2. Double dispatch of the same ambulance and driver.**
- Where: `main.py:105-122` checks only that the vehicle and driver exist. `main.py:157-160` gives the driver only the newest non-terminal mission.
- Scenario (reproduced): two missions on the same vehicle and driver both return 201. The driver app shows only the second. The first can still be advanced via the API, and once it reaches TRANSPORTING_PATIENT it can be neither cancelled nor seen on the driver's screen.
- Fix (2-4 h): return 409 when the vehicle or driver has a non-terminal mission. Back it with a partial unique index on Postgres (`... ON missions(assigned_vehicle_id) WHERE status NOT IN ('COMPLETED','CANCELLED')`, same for driver) so two dispatchers cannot race past the check.

**B3. No dispatcher override after the patient is on board.**
- Where: `state_machine.py:42-44` (dispatchers may only CANCEL), `state_machine.py:20-21` (no CANCELLED after AT_SCENE).
- Scenario (reproduced): mission in TRANSPORTING_PATIENT. Dispatcher cancel returns `409 TRANSPORTING_PATIENT -> CANCELLED`, and AT_HOSPITAL returns `403 driver only`. If the driver's phone dies, is stolen, or the token expires or is revoked (B8, B6), the mission stays "transporting" forever and the vehicle looks busy forever.
- It also makes two documented procedures impossible. `docs/pilot-plan.md:47` says state changes are made "by the dispatcher on their behalf", and `docs/pilot-plan.md:48` says outage missions "are back-filled afterwards by the dispatcher". `docs/runbook-downtime.md:24` says "close missions that finished while down". None of these can be done.
- Fix (3-6 h): let a dispatcher make any forward transition with a required reason and an optional real event time. Audit it as `on_behalf_of` the driver. Keep the driver-only rule for the driver's own token.

**B4. Wrong phone clock = silent loss of all tracking.**
- Where: `main.py:267-271` rejects `ts` more than 60 s ahead or 300 s behind server time. `web/driver/app.js:84-85`: a 422 is neither queued nor shown.
- Scenario (reproduced server side): pings with the phone clock +2 min or -6 min both return 422. Cheap Android phones with manual time or a dead RTC are common. The driver sees nothing wrong. The dispatcher sees "STALE" and assumes no signal.
- Fix (1-2 h): since the server already clamps to receive time (`main.py:282-284`), accept the ping, store the server receive time, and log the skew. Show the driver a message when skew exceeds 60 s.

**B5. One mis-click cancels a live emergency.**
- Where: `web/dispatcher/app.js:71-72` renders "-> CANCELLED" as a plain button next to "Audit". `app.js:91-94` sends it with no confirmation. CANCELLED is terminal (`state_machine.py:23`).
- Scenario: the dispatcher means to click "Audit" on a busy table refreshing every 5 s and cancels the mission. It cannot be undone. The driver's screen silently flips to "No mission" (B15).
- Fix (30 min): confirm with the mission's address in the prompt; require a reason; make the cancel button visually distinct.

**B6. Dispatcher tokens cannot be revoked.**
- Where: revoke exists only for drivers (`main.py:328-333`, via `driver_user()`, `main.py:314-318`). `bootstrap.py` can only add users. Probe: `POST /drivers/{dispatcher_id}/token/revoke` returns 404.
- Scenario: a dispatcher's token leaks (a shared PC, a screenshot). The thief calls `POST /me/token/rotate` (`main.py:320-322`). The real dispatcher is locked out, and the thief holds a 90-day admin credential. Recovery needs a hand-written SQL update on the production database.
- Fix (2 h): an admin-only revoke for any user plus `python -m app.bootstrap revoke USER_ID`. Longer term: split "admin" (mints tokens) from "dispatcher".

**B7. Driver with no vehicle pings `/vehicles/null`.**
- Where: `main.py:73-74` makes both fields optional. `main.py:154` returns `vehicle_id: null`. `web/driver/app.js:83` posts to `/vehicles/${me.vehicle_id}/pings`. `main.py:263-266` answers 403, and `app.js:85` ignores it.
- Scenario (reproduced): the mission is created with a driver and no vehicle. The driver app shows an active mission and runs GPS, but every ping is refused with nothing on screen. Worse: in my run, giving a busy driver a second, vehicle-less mission switched his app's vehicle to null, so the first mission's tracking also stopped.
- Fix (1 h): require a vehicle whenever a driver is set (and vice versa), or derive the vehicle from a driver-shift record.

**B8. Synchronised token expiry.**
- Where: `db.py:108-109` (90 days from creation). `migrations/versions/0004_token_expiry.py:14-15` gives every existing user the identical expiry.
- Scenario: a pilot onboards all 15 drivers on one morning. On day 90 all of them get 401 within minutes, the app signs each one out and wipes their queued pings (`web/driver/app.js:41`, `:45`), and the dispatcher must hand-deliver 15 new 43-character tokens while running dispatch. The 7-day banner (`app.js:108`) helps only if drivers read it.
- Fix (1 h): sliding expiry (extend on use), or stagger with jitter, plus a console list of "expires within 7 days".

**B9. Offline replay may tag old pings with the new vehicle.** Suspected.
- Where: queued pings carry no vehicle or mission id (`web/driver/app.js:78`, `:54`). On reconnect, `app.js:173` calls `replay()` before `load()`, and replay reads the live `me.vehicle_id` on every iteration (`app.js:62`).
- Scenario: the driver goes offline, the dispatcher cancels and reassigns him to vehicle V2, and he reconnects. The first replayed ping goes to V1 (403, dropped). Later ones may go to V2 after `load()` updates `me`, putting V1's track on V2.
- Fix (1 h): store `vehicle_id` and `mission_id` in each queued ping and drop entries that do not match the current mission.

**B10. Fail-open database default.**
- Where: `main.py:28` and `bootstrap.py:34` fall back to `dev.db`.
- Scenario: someone runs the image without `AMBULANCE_DB_PATH` (a typo in compose, a second deployment). The app starts happily on a SQLite file inside the container, and the data disappears on the next recreate.
- Fix (15 min): require the variable unless `AMBULANCE_DEV=1`.

**B11. `notes` silently dropped.**
- Where: `main.py:86` accepts it; nothing stores it. The OpenAPI example is "Patient vitals stabilized, oxygen on at 10L/min" (`openapi.yaml:433-435`).
- Reproduced: the PATCH with notes returns 200, and the notes appear in neither the mission nor the audit. A client that relies on it loses data. If it is ever stored, it is health data (section 11).
- Fix: remove the field from the API and spec now.

**B12. Create and audit are not atomic.**
- Where: `add_vehicle` and `add_user` commit inside (`bootstrap.py:22`, `bootstrap.py:29`), then `main.py:201-202` and `main.py:214-215` write `auth_audit` in a second transaction.
- Scenario: the process dies or the DB drops between the two commits, leaving a driver with a live token and no audit row. Rare, but this is the audit table.
- Fix (30 min): move the commits out of the helpers.

**B13. NaN in an authenticated body returns 500.**
- Where: `PingIn` / `MissionIn` validation. FastAPI echoes the invalid input in the 422 body, and JSON-encoding NaN then fails ("Out of range float values are not JSON compliant" in the server log).
- Reproduced: a ping with `"lat": NaN` returns 500. An unauthenticated request gets 401 first, so only token holders can trigger it. Impact: log noise and a misleading 5xx (the driver app treats 5xx as "queue and retry", `app.js:85`).
- Fix (30 min): a `RequestValidationError` handler that does not echo the input.

**B14. Revoked drivers remain assignable and invisible.**
- Where: `main.py:112-114` checks only that the driver exists. `main.py:206-209` returns no revoked or expiry field.
- Reproduced: I revoked a driver, and a new mission assigned to him returned 201.
- Fix (1 h): reject with 422, and show the revoked/expiry state in the console.

**B15. Cancelled mission disappears without explanation.**
- Where: `web/driver/app.js:104` sets `mission = null` on 404 with no message.
- Scenario: a driver racing to a pickup sees "No mission" with no reason. Was it cancelled? Did the app break? He will phone the dispatcher, which is the right fallback, but the app should say "Cancelled by dispatcher".
- Fix (1 h): return the last mission when it is terminal and less than 10 minutes old, and show its state.

---

## 4. Corner cases and failure modes

| Case | What happens | Status |
|---|---|---|
| Concurrent dispatch of the same ambulance | Not a race: there is no check at all. Both 201 (B2). | Confirmed, reproduced |
| Concurrent status change by dispatcher and driver | Compare-and-set; one wins, the other gets 409; one audit row. | Confirmed (test + code) |
| Double-tap on a driver step | Confirm dialog. The "No" button lands where the step button was (screenshot), so a double-tap cancels the dialog: the safe direction. A second PATCH would get 409 and reload. | Confirmed |
| Illegal transitions | All 49 pairs tested (`tests/test_state_machine.py:17-24`). Terminal states are final. | Confirmed |
| Driver offline | Status changes refused with a message (`app.js:127`). Pings queued in localStorage, max 200. | Confirmed |
| Offline longer than 5 min | Queued pings older than 300 s are dropped by the client (`app.js:59`) and refused by the server (`main.py:270`). The message says "locations are being saved" (`app.js:9`, `:16`), which is false after 5 min. | Confirmed |
| Flaky 2G/3G ("lie-fi": connected but no data) | `fetch` has no timeout (`app.js:40`; no AbortController anywhere). A status tap can hang with no spinner for the browser's default timeout (minutes). | Confirmed (no timeout); real-network behaviour Suspected |
| Phone screen off / app in background | Web pages get no geolocation in the background on Android Chrome, and there is no Wake Lock (none in `web/`). Tapping "Navigate" (`app.js:141`) opens Google Maps and backgrounds the PWA, so tracking likely stops exactly while the ambulance is driving. | Suspected (strong; platform behaviour, not tested on a device) |
| New mission arrives | The driver learns of it only on the next 15 s poll (`app.js:175`), with no sound, vibration or notification. Background tabs are throttled. Dispatchers will still have to phone every driver. | Confirmed (code) |
| GPS jitter | No accuracy field is sent (`app.js:78` drops `coords.accuracy`), so the dispatcher cannot tell a 1.5 km cell fix from a 5 m GPS fix. No smoothing. | Confirmed |
| Spoofed pings | Range-checked only. `(0,0)` accepted; London (8,000 km jump in 1 s) accepted and shown as the vehicle's position. Any driver on an active mission can post any location. | Confirmed, reproduced |
| Clock skew | B4. | Confirmed |
| Token expiry mid-mission | 401: the app signs out, wipes the queue, and the mission is stranded until the dispatcher rotates a token and the driver retypes it (B3, B8). | Confirmed (code) |
| Token kept in `sessionStorage` | Closing the installed PWA (swiping it away) loses the token, and the driver must re-enter 43 characters (`app.js:29`, `:150`). | Confirmed (code) |
| DB down (Postgres) | Requests block on `pool.getconn()` (psycopg_pool default timeout 30 s) and then 500. No health endpoint, so Caddy keeps routing. | Suspected (library default, not run) |
| DB down (SQLite) | 5 s lock timeout (`db.py:92`) then 500. | Confirmed (code) |
| Restart mid-mission | Fine: state is in the DB. Ping-limit pruning runs only at start (`main.py:37-39`). In-flight requests fail and the driver app retries on its next poll. | Confirmed (code) |
| Timezone | Stored in UTC. Console "Updated" column shows a local time with no date (`dispatcher/app.js:78`); yesterday's mission looks like today's. The audit drawer shows raw UTC ISO strings (`app.js:109`), so a Dhaka dispatcher must add 6 hours. | Confirmed |
| Bangla input | Round-trips unchanged (reproduced). The 200-char cap counts code points. A long unbroken string pushes Vehicle/Driver/Actions off-screen at 1280 px (screenshot). | Confirmed |
| Phone numbers | Not collected anywhere. Good for privacy, but the driver cannot call the patient's family. When added: normalise `01XXXXXXXXX` / `+8801XXXXXXXXX` (11 digits after the 0). | Confirmed (absent) |
| Very long history | B1. `vehicle_pings` grows forever (no retention job; `docs/pilot-plan.md:38` admits it). | Confirmed |
| Two dispatchers | Equal superusers; no locking beyond compare-and-set; both can mint driver tokens. | Confirmed |

---

## 5. Security and privacy

**Sound**
- Bearer tokens: 256-bit, hashed, looked up by hash, with expiry and driver revoke. Self-rotation cannot undo a revoke (`main.py:302-312`).
- Role checks are centralised and correct for driver-vs-dispatcher. A driver cannot list, create, cancel, or ping a vehicle not on his mission (probed).
- Same-origin only, no CORS middleware, and the token travels in a header: no CSRF surface.
- All SQL is parameterised. The two f-strings (`main.py:159`, `main.py:264`) only build `?` lists from constants.
- No tokens or addresses in the access log, only IDs.
- No patient data fields exist. That is the right choice before counsel review.

**Gaps**

| # | Issue | Where | Status |
|---|---|---|---|
| S1 | Dispatcher token cannot be revoked; self-rotate locks out the owner (B6). | `main.py:320-333` | Confirmed |
| S2 | "Dispatcher" is also admin: it can mint, rotate and revoke driver tokens. A dispatcher who rotates a driver's token can then act as that driver, and `mission_audit` attributes those moves to the driver. `auth_audit` shows the rotation, but nobody reads it (no UI). | `main.py:324-326`, `main.py:101-103` | Confirmed |
| S3 | Token delivery is manual: the console prints the token in the page (`dispatcher/app.js:98`, `:151`). In practice it will be sent by WhatsApp or SMS and stay in chat history, valid for 90 days. | | Confirmed (code); usage Suspected |
| S4 | No security headers: no CSP, HSTS, X-Frame-Options, Referrer-Policy or nosniff (probed `/console/`; the Caddyfile adds none). | `Caddyfile` | Confirmed |
| S5 | `/docs` and `/openapi.json` are public (FastAPI defaults). They map the whole API for anyone. | `main.py:35` | Confirmed |
| S6 | Audit tables are ordinary mutable rows. The app connects as the Postgres superuser (`docker-compose.yml`, `AMBULANCE_DB_PATH: postgresql://postgres:...`). No append-only role, no hash chain, no IP or user agent recorded. "Full audit trail" (pitch) is true only against honest admins. | `migrations/versions/0001_initial.py:32-36` | Confirmed |
| S7 | Compose accepts the `.env.example` placeholder password. The DB is not published on a port, so the impact is low, but it breaks the house rule. | `docker-compose.yml`, `.env.example` | Confirmed |
| S8 | GPS spoofing is unchecked (section 4). This matters for any future "proof of response" or billing use. | `main.py:259-286` | Confirmed |
| S9 | The test fixture terminates every other session on, and drops the `public` schema of, whatever `TEST_DATABASE_URL` points at. One wrong environment variable on a shared host wipes production. | `tests/conftest.py:15-20` | Confirmed (code) |
| S10 | Rate limits exist only on pings. Fine for token guessing (256-bit), but a compromised dispatcher token can create unlimited missions and drivers. | | Confirmed |
| S11 | No human has reviewed any of this. The "agent self-review" in `judge.md` Update 11 is not a review. | | — |

**Privacy.** The only personal data held: driver names, driver location (personal data under the 2025 ordinance, section 11), and free-text pickup addresses. Dispatchers will type names and phone numbers into the address field, because there is nowhere else to put them. Ping retention is unlimited. The pilot plan promises 90 days (`docs/pilot-plan.md:38`), and no deletion job exists.

---

## 6. UI

Screenshots taken at 375x812 (driver, console) and 1280x800 (console) in Chromium.

**Driver app: the best part of the project.**
- Black background, white and yellow, 18 px base, 56-72 px buttons (`web/driver/styles.css:2-8`). This will read well in sunlight on a cheap screen. Bangla is the default with a one-tap English toggle. Status labels are translated. There is an `aria-live` status region.
- One big yellow next-step button, plus a confirm dialog with big Yes/No buttons. Good.
- Problems:
  - The top of the card is an 8-hex-digit mission ID ("#2f46c412"), which is useless to a driver. Show the pickup and the elapsed time first.
  - No patient or caller contact, no notes, no dispatch time.
  - Login is a password-type field for a 43-character random token (`app.js:149`). The driver cannot see what he types. This is the worst screen in the product.
  - "Sign out" sits next to "Refresh", and one tap logs out and wipes queued pings with no confirmation (`app.js:165`, `:169`, `:45`).
  - Error lines stack in a yellow/red box above the card. With the token-expiry banner, an offline line and a GPS line, the mission is pushed down.

**Dispatcher console: not fit for a control room yet.**
- English only (`index.html:2`). 14 px body and 12 px labels (`style.css:1`, `:7`). Status shown as raw `TRANSPORTING_PATIENT` codes.
- No map. Vehicle positions are printed as "23.80000, 90.36000 (12 s ago)" text. A dispatcher cannot see which ambulance is nearest.
- The new-mission form requires latitude and longitude and makes the address optional (`index.html:22-24`). This is backwards for phone-call dispatch. Callers give landmarks.
- Missions are listed oldest first, so the newest is at the bottom of a list that, after B1, may not contain it.
- Every idle vehicle shows red "no ping (STALE)", because pings are accepted only during a mission (`main.py:263-266`, `dispatcher/app.js:48`). In a 20-vehicle fleet, 15+ rows are red all day. Dispatchers learn to ignore red.
- No elapsed-time column and no highlight for "DISPATCHED for 3 minutes with no acknowledgement", which is the single most useful alarm.
- Error toasts show raw strings ("409: TRANSPORTING_PATIENT -> CANCELLED") and vanish after 6 s.
- At 375 px the console is usable for reading, but the table scrolls sideways and the actions are off-screen.

---

## 7. UX: real workflows under stress

**Dispatcher, one emergency call, today:**
1. Take the call ("Mirpur 10, behind the mosque").
2. Open Google Maps in another window and find the place.
3. Copy the latitude, paste it. Copy the longitude, paste it.
4. Type the address.
5. Pick a vehicle by registration, without seeing which ones are free or near.
6. Pick a driver separately, hoping the pairing is right.
7. Click Create. After 200 missions, nothing appears (B1).
8. Phone the driver anyway, because the app does not alert him.

That is 10+ actions and a second app, then the same phone call they make today. The pilot's own criterion "faster or equal to phone/radio" fails on step 2.

**Driver:** sign in (43 characters, blind) → wait for a poll → tap step + confirm, four times = 8 taps per mission. The tap count is fine. But the pilot plan forbids touching the phone while moving (`docs/pilot-plan.md:47`), so the "at scene" and "at hospital" taps will be late or skipped. The designed fallback (dispatcher taps on his behalf) does not exist (B3).

**When things go wrong:**
- Mission cancelled: the driver silently sees "No mission" (B15).
- Phone clock wrong: nothing visible (B4).
- Token expired: logged out and the queue wiped.
- Patient on board and phone dead: the mission is stuck forever (B3).
- System down: the runbook is clear and correctly says "phone first", but its recovery step cannot be executed (B3).

**Onboarding:** the first dispatcher is created by a CLI on the host. Each driver gets a token read out or messaged by the dispatcher. No QR pairing, no short code, no "install this app" guidance. For 15 drivers with mixed literacy this is a half-day of support for the owner.

---

## 8. Accessibility and performance

**Performance on low-end phones: good.** The driver shell is about 14 KB (app.js 11.9 KB, HTML 0.8 KB, CSS 1.3 KB; measured), with no framework and no fonts. The service worker caches the shell network-first (`sw.js:11`).

**Bandwidth: two real problems.**
- **Console:** `/missions` returned 59 KB at 200 missions, polled every 5 s (`dispatcher/app.js:126`), uncompressed (no gzip from the app, no `encode` in `Caddyfile`; confirmed by request). That is about 1 GB/day per console left open, which is significant on a mobile-data dongle. Fix: an active-only view (B1) plus `encode gzip` in Caddy.
- **Driver:** three requests every 15 s while the app is open (`/me`, `/missions/current`, `/meta/transitions`), about 1.2 KB of body plus headers per cycle, measured. That is roughly 7 MB/day in the foreground before TLS overhead (estimate). `/meta/transitions` never changes and should be fetched once.

**Battery:** high-accuracy GPS runs only during a mission (good). Idle polling keeps the radio awake while the page is visible.

**Accessibility:**
- Driver: the `lang` attribute switches with the toggle (`app.js:145`), focus-visible outlines (`styles.css:18`), and big targets. A dialog is `aria-label`-ed.
- Console: labelled form fields and `role=alert` toasts. "STALE" is text, not colour only (good). Tables have no captions, and the 12 px labels are too small.
- No audio cue anywhere. For drivers, an audible new-mission alert is both an accessibility and a safety need.
- Untested: TalkBack, large-font settings, Bangla font rendering on old Android WebViews.

---

## 9. Testing and verification

**What the tests prove** (109 pass on SQLite locally; CI shows Postgres green on the last 5 pushes):
- the state machine allows exactly the intended 8 transitions;
- the role rules hold at the API;
- compare-and-set yields one winner under 8 threads;
- the ping rate limit holds across 4 app instances on one DB;
- token rotate, revoke and expiry work, and self-rotate cannot undo a revoke;
- responses match the OpenAPI schemas;
- migrations keep data from 0001 to 0004;
- migrations are safe with concurrent starters on Postgres (that test is skipped without a Postgres URL; CI runs it).

**What they do not prove**

| Gap | Why it matters |
|---|---|
| Anything over 200 missions; the test asserts the buggy order (`tests/test_api.py:167-171`). | B1 ships with a green test. |
| Double assignment, driver without vehicle, revoked-driver assignment. | B2, B7, B14 untested. |
| Clock skew on the client; 422 handling in the app. | B4. |
| Dispatcher revoke / lockout. | B6. |
| Real phones, background tab, screen off, Navigate to Maps. | The core "live visibility" promise. |
| Service worker: every e2e context uses `service_workers="block"` (`tests/e2e_browser.py:112`, `:170`, `:211`). | The "offline app" claim has no test. |
| Safari/WebKit and Firefox. | I could not run WebKit (browser build mismatch); untested. |
| e2e is not in `check.sh` or CI. | 37 checks run only when someone remembers. |
| Docker image build, Caddy, HTTPS, compose. | The deploy path has never executed once. |
| DB outage, restore from backup, load beyond toy size. | Ops claims are untested. |

The 109 count is inflated by 49 parametrised state pairs. That is fine, but the real behavioural coverage is about 40 tests.

---

## 10. Deploy and operations

| Item | State |
|---|---|
| Host | None. Compose, Caddyfile and Dockerfile are marked UNTESTED; the image has never been built. |
| Reproducible build | No. Dependencies are unpinned (A8). |
| Health check | None. No `/healthz`; compose has none for `app`; Caddy has no upstream check. |
| Backups | None. `docs/deploy.md` step 6 says "back up the volume"; there is no job, no offsite copy, and no restore drill. |
| Monitoring / alerting | None. No uptime check and no error tracking. Logs are only container stdout. |
| Rollback | Untagged `build: ./backend`. Migrations auto-run at start; they are additive, so rolling the image back mostly works, but nothing is documented. |
| Staging | None, though `docs/mvp-wedge.md` asks for one "from day one". |
| Time sync | Ping validation depends on the server clock. Fine on any cloud VM; note it for a self-hosted box. |
| On-call | One person, the owner, with no rota, no pager and no escalation. |

For a safety-adjacent tool this is acceptable only because the design is advisory and "phone first", and the runbook says so plainly (`docs/runbook-downtime.md`). That design choice is the project's best safety decision. Keep it in every agreement. But it means the pilot must budget for a human (the owner) who answers the phone within minutes during pilot hours. That is the real ops cost, not the VM.

---

## 11. Legal and compliance (Bangladesh)

I am not a lawyer; this lists what counsel must check.

- **Data protection is no longer "UNKNOWN".** The repo calls the law UNVERIFIED (`docs/pilot-plan.md:28`). In fact a Personal Data Protection Ordinance 2025 was approved on 9 Oct 2025 and gazetted on 6 Nov 2025. It treats health records as sensitive data, requires explicit consent, has cross-border transfer rules, and some sections start 18 months after gazetting (about May 2027). Its status after the 2026 elected parliament (ordinances need ratification) must be confirmed. Name it in the docs and ask counsel the specific questions: is driver location personal data (almost certainly), is hosting outside Bangladesh allowed, and what consent wording and retention period are required. ([Daily Star](https://www.thedailystar.net/tech-startup/news/bangladeshs-personal-data-protection-ordinance-2025-key-takeaways-4015401), [TBS](https://www.tbsnews.net/node/1281356))
- **Health data:** none is collected by design. Keep it that way: remove `notes` (B11) and add a visible warning on the address field ("no patient names or numbers").
- **Ambulance operator regulation:** there is still no comprehensive ambulance policy. A DGHS draft has bounced between DGHS and the ministry since 2017. BRTA registers ambulances, and DGHS has no regulatory control. The High Court's 2018 EMS guidelines for road-crash victims carry the force of law until legislation. So there is no licence to check, but also no rule that protects a dispatch-software vendor. ([Dhaka Tribune](https://www.dhakatribune.com/bangladesh/13250/ambulance-policy-yet-to-be-okayed), [Prothom Alo](https://en.prothomalo.com/bangladesh/4l3eiqusze), [Bangladesh Health Watch](https://bangladeshhealthwatch.org/events/roundtable-discussion-on-guidelines-and-implementation-of-emergency-medical-services))
- **GPS mandate:** a June 2026 gazette, under Road Transport Act 2018 s.25, requires GPS devices on public transport vehicles from 1 Aug 2026, with 26 BRTA-authorised tracking providers. Whether ambulances fall under "public transport" must be checked. If they do, every ambulance will carry a hardware tracker, which changes the product (section 12). ([Jago News](https://www.jagonews24.com/en/national/news/94795), [Bonik Barta](https://en.bonikbarta.com/bangladesh/brQvjM00bCIKBfPX))
- **Liability:** Apache 2.0's warranty disclaimer covers the code, not a hosted service the owner operates. The pilot needs a written agreement: advisory only, the operator remains responsible for dispatch, the owner's liability is capped, there is an incident-reporting duty, and data roles (operator = controller, owner = processor) are stated. B1-type failures ("the mission was in the system but nobody saw it") are exactly the incident that agreement must anticipate.
- **Employment:** driver tracking used for discipline is the predictable conflict. The pilot plan's "no discipline unless agreed" clause is good. Get it signed, in Bangla.

---

## 12. Market, demand and marketability

**Who actually pays?**

| Candidate | Likelihood | Note |
|---|---|---|
| Private hospital fleets | Medium | They have the pain (coordination, accountability) and some budget. Ad-din's Dhaka service reports 61 ambulances, each with a vehicle tracking device and a control room that directs the nearest one. The best-run buyers already have tracking. ([Ad-din](https://awmch.addinhospital.org/?p=448)) |
| NGO / charity fleets (e.g. Anjuman Mufidul Islam) | Medium for a free pilot, low for revenue | Donors value an audit trail and response-time data; that is the honest wedge. |
| App-based ambulance services (URAL EMS since 2018) | Low | They are competitors with their own app and call centre. ([Financial Express](https://old.thefinancialexpress.com.bd/public/print/ural-ems-launches-first-app-based-ambulance-service-in-country-1534684735)) |
| District administrations (e.g. "Swapnojatra", Lakshmipur) | Low-medium | Public-sector precedents exist; procurement is slow, but a free open-source pilot can bypass it. ([Prothom Alo](https://en.prothomalo.com/amp/story/bangladesh/good-day-bangladesh/low-cost-app-for-ambulance-service)) |
| 999 (police-run) | Very low near-term | 999 forwards to ambulance providers; integration needs a government agreement. ([Daily Star](https://online.thedailystar.net/node/1503907)) |
| Syndicate-controlled hospital-gate ambulances | Hostile | The syndicates control demand at public hospitals and resist outside vehicles; one case ended in a newborn's death. Tracking and fare transparency threaten their margins. ([Daily Star editorial](https://www.thedailystar.net/opinion/editorial/news/break-the-syndicate-ambulance-owners-3290056), [Prothom Alo](https://en.prothomalo.com/bangladesh/q0k4wsvb0o)) |
| Insurers | Very low | Not a meaningful payer for ambulance trips in Bangladesh today. |

**Real alternatives the operator already has**
1. Phone and WhatsApp groups: free, instant, already trained.
2. BRTA-authorised hardware GPS trackers: ৳400-600 per vehicle per month at retail, and fleet SaaS such as LocomotePro from ৳499 per vehicle per month. They track with the phone off and need no driver action. ([LocomotePro launch](https://meatechwatch.com/2026/07/27/locomotepro-launches-in-bangladesh-as-the-1-august-gps-mandate-arrives/), [Rokomari listing](https://www.rokomari.com/electronics/173490/prohori-gps-tracker-basic-package))
3. In-house booking apps (URAL EMS; a hospital iOS app with ambulance request, Oct 2025).

**Why anyone would switch.** Not for "live positions": a ৳500 tracker does that better than a phone PWA. The only differentiators are the mission state trail (who was sent, when acknowledged, when on scene) and the resulting response-time data. That is valuable to donors, hospital management and regulators, not to the driver. Positioning should therefore be "accountability and response-time measurement for a fleet", ideally reading positions from the trackers the fleet already has.

**Pricing reality.** The code is Apache 2.0, so there is no licence revenue. A hosted service at ৳300-500 per vehicle per month for 20 vehicles is ৳6,000-10,000 (about US$50-80) a month. That does not pay for one person on call. This is a grant-funded or NGO-partnered project, or a feature inside a larger fleet product. Plan on that basis.

**Demand evidence:** zero interviews, zero LOIs, zero conversations recorded. The pitch's public numbers (999 call volume, Dhaka speed, fire incidents) show the problem exists. They say nothing about whether a fleet coordinator wants this tool.

**Pitch-deck claims vs reality** (`pitch/1.html`)

| Claim | Reality |
|---|---|
| "See live vehicle positions" (`:129`) | Text coordinates, no map; only during a mission; likely stops when the app is backgrounded. |
| "Runs on low-end phones" (`:130`) | Never run on any phone. Should be marked UNVERIFIED. |
| "Offline queue: GPS pings wait and send when signal returns" (`:130`) | Only for 5 minutes; older pings are dropped. |
| "Full audit trail" | Status changes only; mutable rows; no way to record dispatcher actions "on behalf". |
| "Tested in simulation" (`:203`) | No simulation exists, only headless-browser tests with a fake GPS fix. |
| "Fire trucks ... No rebuild" (`:157`) | False. "Multi-vehicle incidents" needs a new data model: a mission has exactly one vehicle (`0001_initial.py:24`). Remove the slide. |
| Contact line (`:59`) | Still the placeholder "YOUR NAME · PHONE · EMAIL". |
| "Nothing here needs a budget" | True for the ask. But the ask (an introduction) is right, and it is the best thing in the deck. |

---

## 13. GTM percentage breakdown

| Dimension (weight) | Mine | Scorecard | One line |
|---|---|---|---|
| Product works (25) | 3 | 5 | The loop runs on a laptop, but B1-B4, lat/lng entry, no driver alert and likely background-GPS loss break real dispatch. |
| Quality and verification (15) | 5 | 7 | Strong API tests and green Postgres CI; a test enshrines B1; no device, SW, Docker or e2e-in-CI. |
| Security and privacy (15) | 5 | 6 | Solid token/role core; no dispatcher revoke, no headers, mutable audit, no retention, no human review. |
| Legal and compliance (10) | 1 | 2 | Nothing done; docs still call a gazetted 2025 ordinance "unknown"; no consent text, no agreement. |
| Market validation (15) | 1 | 1 | Zero interviews, zero LOIs; public problem evidence only. |
| Deploy and operations (10) | 1 | 2 | Never built or hosted; no backups, health check, monitoring or pinned deps. CI is the only real piece. |
| Claims honesty (10) | 5 | 7 | Docs label futures well, but README/roadmap/pilot-plan are stale both ways, the spec still advertises a "National Gateway" with preemption, and the pitch overclaims. |

**Weighted:** 25(0.3) + 15(0.5) + 15(0.5) + 10(0.1) + 15(0.1) + 10(0.1) + 10(0.5) = 7.5 + 7.5 + 7.5 + 1 + 1.5 + 1 + 5 = **31**.
**Cap: 12.** Safety-critical dispatch software with no operator and no field test, plus known defects that fail its own pilot criterion. **Final: 12%.**

**Where I disagree with `judge.md` and the scorecard**
- They score the product as working (5/10). It works for a demo, not for a dispatcher's first week (B1, B2, B3, lat/lng form).
- They frame "real phones" as a test still to run. I expect that test to fail by design: a web page does not get GPS in the background, and the app's own Navigate button backgrounds it. Plan the fix now: an Android wrapper with a foreground service, or reading hardware-tracker feeds.
- `judge.md` Update 13 says Postgres was "not re-run" for `f2d3456`. GitHub CI ran the Postgres step green on that commit (`gh run list`).
- `judge.md` Update 8 item 9 says the spec was rewritten to MVP shapes. The preemption, telemetry and public-availability paths and the `.gov.bd` servers are still in `openapi.yaml`.
- The scorecard's trust note says "Nothing is committed"; everything is pushed.
- Honesty at 7 is generous. `README.md:14-15` says there is no console or driver app and that CI never ran, `docs/roadmap.md:6` and `docs/pilot-plan.md:10` say the same, and `backend/README.md:15` still says the rate limit is in-process. Stale in both directions.

---

## 14. What to cut or stop doing

- **Stop backend hardening rounds** (token polish, pruning, body caps) until a dispatcher has used the console for a day. The last three agent rounds went to security edges while the dispatch loop has B1-B3.
- **Stop self-scoring rounds.** The 18% has not moved in three rounds. Scoring is not progress.
- **Cut the fire-truck slide** and the "multi-vehicle incidents" claim.
- **Park `now.md`'s traffic-light and AI-camera goal** formally. Write one line in the README: "Signals: not this project until the gates are met." Or, if that is truly the owner's goal, stop this repo and start the government conversation, which is the only path to signals.
- **Cut from `openapi.yaml`:** `/telemetry/ingest`, `/preemption/*`, `/ambulances/available`, the `.gov.bd` servers and "Traffic Preemption Platform". Move them to `docs/architecture/` as prose.
- **Cut the `notes` field** and the dead `vehicles.active` check (or add the endpoint).
- **Stop polling `/meta/transitions`**; fetch it once.
- **Fold `web/driver/mock_server.py`** into the real server with a seeded SQLite DB, or delete it. The real server already starts in one second, and a mock that must be kept in sync is a liability.

---

## 15. Top 10 next actions (ordered by value)

| # | Action | Effort | Who |
|---|---|---|---|
| 1 | Sit with 3 fleet coordinators (a private hospital, an NGO such as AMI, an app operator) and watch 5 real calls each. Ask: what do you write down, what do you lose, would you trade the phone for this? Decide in writing: this project or the traffic-light one. | 1-2 weeks elapsed | Owner |
| 2 | Fix the pilot-blockers: B1 (newest-first, active-only console view; fix the test), B2 (409 + partial unique index), B3 (dispatcher "on behalf" transitions with reason and event time), B5 (cancel confirm), B7 (vehicle required with driver). | 1 day | Agent |
| 3 | Run the driver app on 2-3 cheap Androids in a moving vehicle: screen off, Navigate to Maps, 2G areas, wrong clock. Record what stops. | 1 day | Owner |
| 4 | Based on #3, choose the location source: an Android wrapper (TWA/Capacitor) with a foreground location service, or ingest an existing BRTA-approved tracker's feed. Build the chosen one minimally. | 2-5 days | Agent, owner decides |
| 5 | Make dispatch faster than a phone: address-first form, a map with click-to-place pickup and all vehicles (OSM tiles), "free / busy" per vehicle, a driver-vehicle shift pairing, an elapsed-time column and a "not acknowledged in 2 min" alarm. | 2-3 days | Agent |
| 6 | Driver alerting and onboarding: sound and vibration on a new mission, an SMS fallback to the driver's phone, QR or 6-digit pairing instead of a 43-character token, token in `localStorage`, sign-out confirm, "cancelled by dispatcher" message (B15), clock-skew tolerance (B4). | 2 days | Agent |
| 7 | Security minimums before real data: admin revoke for any user (B6), split admin from dispatcher, security headers and `encode gzip` in Caddy, hide `/docs`, a non-superuser DB role with INSERT-only rights on audit tables, ping retention job (90 days). | 1 day | Agent |
| 8 | Stand up staging on a real host: build the image, pin deps with a lock file, add `/healthz`, nightly `pg_dump` offsite with one tested restore, an uptime alert to the owner's phone. Run the compose path once end to end. | 1-2 days | Owner + agent |
| 9 | Counsel review against the Personal Data Protection Ordinance 2025: hosting location, driver consent text in Bangla, retention, and a pilot agreement (advisory-only, liability cap, controller/processor). | 1-2 weeks elapsed, paid | Owner |
| 10 | Human review of auth, audit and the dispatch transitions by one experienced engineer (not an agent), then refresh README/roadmap/pilot-plan/pitch to match the code (remove stale "no UI", "CI never ran", fire slide, contact placeholder). | 1 day review + 2 h docs | Owner hires; agent edits docs |

---

*Skipped / not verified: no real device, no WebKit or Firefox run (browser builds did not match), no Postgres run by me (CI shows it green), no Docker build, no load test. Market figures come from news and vendor pages found by web search and are not independently checked; whether ambulances fall under the BRTA GPS mandate is unconfirmed.*
