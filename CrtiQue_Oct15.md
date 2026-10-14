# Ambulance-AID-BD: independent critique (2026-10-15)

Reviewer: senior engineer / product / go-to-market, independent of `judge.md` and the scorecard.
Scope: git worktree `Ambulance-AID-BD-int`, branch `oct14-int` at `4ceaafa` (39 commits ahead of `origin/main`, not pushed).

**What I did.**
- Read `AGENTS.md`, `CODING_STANDARDS.md`, `README.md`, `judge.md` (last section first), `docs/`, `pitch/1.html`, both web READMEs and `docs/android-wrapper.md`.
- Read all of `backend/app`, `backend/web`, `android/`, `ops/`, the compose file, the Caddyfile, the Dockerfile and migration 0006.
- Ran `scripts/check.sh`: all 7 steps pass, 168 passed and 1 skipped (SQLite).
- Ran the browser e2e: 115 checks pass.
- Ran `./gradlew testDebugUnitTest assembleDebug`: 9 unit tests pass and the debug APK builds.
- Started the server on a scratch SQLite DB, probed it with two scripts, then stopped it.
- Viewed viewport screenshots: console 1280x800, 768x1024 and 375x812; driver app 360x740.
- Did a short web search on the market and the law.

Venv, DB, logs and screenshots are in `scratchpad/crit-ambulance/`. Nothing in the repo was changed except this file. The worktree is clean apart from gitignored build outputs.

Labels: **Confirmed** means I reproduced it or traced the code path end to end. **Suspected** means plausible and partly traced, but not proven (usually Android platform behaviour I could not run on a device).

---

## 0. Since 2026-10-14

Every baseline finding, checked in the code, not in commit messages.

### Bugs B1-B15

| # | Baseline finding | Status | Evidence |
|---|---|---|---|
| B1 | Console hides missions after 200 | **Fixed** | `main.py:286` newest first. `main.py:282-289` `active=true` is unpaged. Console polls `/missions?active=true` (`dispatcher/app.js:166`) and pages history 25 at a time (`app.js:169`). Test `test_b1_*`. |
| B2 | Double dispatch of one ambulance or driver | **Fixed** | Check at `main.py:262-264`, backed by partial unique indexes (`0006_dispatch_loop.py:46-47`). IntegrityError gives 409 (`main.py:270-272`). Reproduced: second dispatch gives 409. |
| B3 | No dispatcher override after AT_SCENE | **Fixed** | `state_machine.py:47-49` `on_behalf()`; `main.py:464-481`. Reproduced: revoked driver, dispatcher walks the mission to COMPLETED, and every audit row carries `on_behalf_of`. |
| B4 | Wrong phone clock means silent tracking loss | **Fixed** | `main.py:503-511`: server receive time minus `sent_at - ts`. Skew returned (`main.py:532`) and shown (`driver/app.js:110`). Reproduced: phone clock +3 h gives 201 with `clock_skew_s: 10800`. |
| B5 | One mis-click cancels a live emergency | **Fixed in the UI** | Cancel dialog with address, required reason and a separate red button (`dispatcher/index.html:87-97`, `app.js:133`). The API still accepts a cancel with no reason (`main.py:469`; reproduced 200). |
| B6 | Dispatcher tokens cannot be revoked | **Fixed** | `POST /users/{uid}/token/revoke` (`main.py:588-592`), CLI `bootstrap revoke` (`bootstrap.py:57-61`), admin split (`main.py:147-151`). No UI for it: neither front end calls `/users`. |
| B7 | Driver without vehicle pings `/vehicles/null` | **Fixed** | `main.py:255-259` takes the driver's paired vehicle or refuses. Driver app shows `noVeh` (`driver/app.js:142-143`). New edge case: an empty-string vehicle id (N11). |
| B8 | All drivers expire in the same minute | **Fixed** | Sliding expiry, written at most once a day (`main.py:134-138`). |
| B9 | Offline replay onto a new vehicle | **Fixed** | Each queue entry carries `vehicle_id` and `mission_id`; `qOk` drops mismatches (`driver/app.js:93`, `:120-121`). Android queue clears on a vehicle change (`TrackingService.kt:74`). |
| B10 | Missing DB env silently uses `dev.db` | **Fixed** | `db.py:109-116`. |
| B11 | `notes` silently dropped | **Fixed** | `extra="forbid"` (`main.py:188`); reproduced 422. |
| B12 | Create and audit not atomic | **Fixed** | Helpers no longer commit (`bootstrap.py:15`). Caller commits once (`main.py:421-423`). |
| B13 | NaN gives 500 | **Fixed** | Handler never echoes input (`main.py:108-112`); reproduced 422. |
| B14 | Revoked drivers assignable and invisible | **Fixed** | `assignable()` (`main.py:210-216`). Console shows the token state (`app.js:112-119`). |
| B15 | Cancelled mission vanishes silently | **Fixed** | `/missions/current` keeps an ended mission for 10 min (`main.py:310-324`). "Cancelled by dispatcher" card (`driver/app.js:266`). |

### Security S1-S11

| # | Baseline finding | Status | Evidence |
|---|---|---|---|
| S1 | Dispatcher token not revocable | **Fixed** | As B6. |
| S2 | Dispatcher is also admin; can impersonate a driver | **Partly fixed** | Admin is split from dispatcher (`main.py:147-151`, migration `0006:17-19`). An admin can still rotate a driver's token ("Show token", `app.js:212-220`) and then act as the driver, and `mission_audit` attributes those moves to the driver. `auth_audit` records the rotation, but nothing reads it (no endpoint, no UI). |
| S3 | Raw 43-character token sent over chat | **Fixed** | 6-digit or QR pairing code, 10 min, one use (`main.py:594-630`). The console drops the create-response token (`app.js:301`). The raw "Show token" path remains behind a warning. |
| S4 | No security headers | **Fixed (laptop only)** | `Caddyfile:6-16`: CSP, HSTS, nosniff, XFO, Referrer-Policy, Permissions-Policy. The e2e runs the console under this CSP. |
| S5 | `/docs` public | **Fixed** | `main.py:95-97`; probed 404. |
| S6 | Mutable audit rows, app connects as superuser | **Partly fixed** | Least-privilege `ambulance_app`; `*_audit` tables are INSERT/SELECT only for it (`ops/migrate.py:21-34`). The superuser password sits in the same `.env` (used by backup). There is no hash chain and no IP is recorded. The `missions.*_at` times, which are the response-time data, stay mutable. |
| S7 | Placeholder Postgres password accepted | **Fixed** | `docker-compose.yml:9-17` refuses placeholders, short passwords and non-alphanumeric ones. |
| S8 | GPS spoofing unchecked | **Partly fixed** | (0,0) and impossible jumps refused (`main.py:509-518`; reproduced a 17 km jump in 1 s: 422). A plausible fake track still passes. No mock-location check on Android (`TrackingService.kt:101-107`). |
| S9 | Test fixture can wipe any DB | **Fixed** | The name must contain "test" (`tests/conftest.py:9-19`). |
| S10 | No create rate limits | **Fixed (mostly)** | 30 creates per minute per token on missions, drivers and users (`main.py:165-169`). Not on vehicles. |
| S11 | No human review | **Still open** | No human has reviewed auth, pairing, the bridge or the service. |

### Architecture A1-A10

| # | Finding | Status | Evidence |
|---|---|---|---|
| A1 | Everything inside `create_app()` | **Still open, worse** | 339 to 636 lines (`main.py:65-636`). |
| A2 | Helpers commit on their own | **Fixed** | `bootstrap.py:15`. |
| A3 | TEXT timestamps | **Still open** | Now more columns are compared as strings (`main.py:475`). Safe while every writer uses `now()`'s format. |
| A4 | `?` to `%s` string replace | **Still open** | `db.py:67`. Low risk. |
| A5 | `vehicles.active` dead | **Fixed (API only)** | `PATCH /vehicles/{vid}` (`main.py:384-390`). No console button. |
| A6 | Dead `notes` | **Fixed** | As B11. |
| A7 | OpenAPI described another product | **Fixed** | `openapi.yaml:1-12`. No preemption, telemetry or `.gov.bd` paths remain. |
| A8 | Unpinned deps, test tools in image | **Partly fixed** | Docker uses the hashed `requirements.lock` (`Dockerfile:3-4`); test deps moved out. CI and `check.sh` install unpinned `requirements-dev.txt`, so tests run on different versions than production. |
| A9 | No driver-vehicle pairing | **Fixed** | `vehicles.driver_id` unique (`0006:21-22`); `PUT /vehicles/{id}/driver` (`main.py:392-405`). |
| A10 | No tenant concept | **No longer applies** | "One fleet per deployment" is stated (`openapi.yaml:6`). `CODING_STANDARDS.md` still asks for an operator-ownership check that cannot exist. |

### Corner-case rows

| Case (baseline) | Status | Evidence |
|---|---|---|
| Concurrent dispatch of one ambulance | **Fixed** | Unique index; test `test_b2_concurrent_dispatch_has_one_winner`. |
| Concurrent dispatcher and driver status change | Still fine | Compare-and-set (`main.py:452-456`). |
| Double-tap on a driver step | Still fine | Confirm dialog; a second PATCH gives 409 and a reload (`driver/app.js:229`). |
| Illegal transitions | Still fine | `state_machine.py:16-24`; parametrised tests. |
| Driver offline | Unchanged | Status changes are refused offline (`driver/app.js:224`). |
| Offline longer than 5 min | **Fixed (honesty)** | The text now says "kept for up to 5 minutes" (`driver/app.js:14`, `:29`). The limit itself stays (`main.py:507-508`; reproduced: a 6-minute-old fix gives 422). |
| Flaky 2G/3G, no fetch timeout | **Fixed** | 10 s AbortController (`driver/app.js:58-63`). Native uses 10/15 s timeouts (`TrackingService.kt:128-129`). |
| Screen off or app in background | **Partly fixed** | The Android wrapper's foreground service; emulator only (`docs/android-wrapper.md:93-100`). Background start is unsafe (N3). |
| New mission arrives with no alert | **Partly fixed** | Siren, vibration and notification work only while the page is on screen. None in the wrapper's background (N1). SMS is optional. |
| GPS jitter, no accuracy | **Fixed** | Accuracy sent, stored and drawn as a circle (`main.py:198`, `app.js:88`). Native drops fixes worse than 100 m (N9). |
| Spoofed pings | **Partly fixed** | As S8. |
| Clock skew | **Fixed** | As B4. The console still uses the PC clock for the ack alarm (N13). |
| Token expiry mid-mission | **Fixed** | Sliding expiry plus on-behalf moves. |
| Token in `sessionStorage` | **Fixed** | `localStorage` (`driver/app.js:47-48`). |
| DB down (Postgres) | **Fixed** | `/healthz` (`main.py:234-242`); Caddy health check gives 503 (`Caddyfile:17-21`); verified on a laptop (`docs/deploy.md:86`). The pool still waits 30 s. |
| DB down (SQLite) | Unchanged | 5 s lock timeout (`db.py:93`). |
| Restart mid-mission | Fine | State is in the DB; prune is now daily (`main.py:83-90`). |
| Timezone | **Fixed** | Dhaka time everywhere in the console (`app.js:46-49`). |
| Bangla input | Fine | Bangla address round-trips (probe). Bangla digits accepted in phone and pairing code (`main.py:41`, `:46`, `:53`). |
| Phone numbers | **Fixed** | `bd_phone()` (`main.py:44-49`); reproduced `০১৭১১-২২৩৩৪৪` to `+8801711223344`. |
| Very long history, pings forever | **Fixed** | 90-day retention, daily (`main.py:78`, `:83-90`). |
| Two dispatchers as equal superusers | **Partly fixed** | Admin and dispatcher split. Any dispatcher can still change a driver's phone with no audit (N10). |

### Pitch claims

| Claim (baseline) | Status | Evidence |
|---|---|---|
| "See live vehicle positions" | **Partly fixed** | Now "Vehicles on a map, free, busy or stale" (`pitch/1.html:124`). "Free" is almost never true: idle vehicles cannot send positions (N2). |
| "Runs on low-end phones" | **Fixed** | Marked UNVERIFIED (`pitch/1.html:113`, `:125`). |
| Offline queue | **Fixed** | "up to 5 minutes old ... older ones are dropped" (`:125`). |
| "Full audit trail" | **Fixed** | "Status-change audit trail" (`:126`). |
| "Tested in simulation" | **Fixed** | Now "headless browsers and an Android emulator" (`:124`). |
| Fire trucks, "no rebuild" | **Fixed** | Slide removed. |
| Contact placeholder | **Still open** | `pitch/1.html:59` `"OWNER TODO: name · phone · email"`. |
| "Nothing here needs a budget" | No longer applies | The ask is right. New nit: "automatic 90-day expiry" (`:128`) is now 90 days after last use. |

### Top-10 actions

| # | Baseline action | Status |
|---|---|---|
| 1 | Sit with 3 fleet coordinators; decide this project or traffic lights | **Still open.** Zero interviews. Signals are parked in the README (`README.md:37`), but there is no owner decision on record. |
| 2 | Fix B1, B2, B3, B5, B7 | **Fixed.** |
| 3 | Run on 2-3 cheap Androids in a moving vehicle | **Still open.** Emulator only. |
| 4 | Choose a location source and build it minimally | **Done (emulator).** Android wrapper with a foreground service. Not on a device. |
| 5 | Make dispatch faster than a phone | **Mostly done.** Address-first form, map with click-to-place, busy/free, pairing, elapsed time, 2-minute ack alarm. Missing: address search, and fresh positions for free vehicles (N2). |
| 6 | Driver alerting and onboarding | **Mostly done.** Siren, vibration, SMS, 6-digit/QR, `localStorage`, sign-out confirm, B4, B15. Missing: an alert that reaches a phone in a pocket (N1). |
| 7 | Security minimums | **Done.** Admin revoke, role split, headers, gzip, docs hidden, least-privilege role, retention. |
| 8 | Staging on a real host, lock file, healthz, backups, uptime alert | **Partly done.** Lock, healthz, nightly local dumps and the restore drill ran on a laptop. No host, no offsite copy, no alert. |
| 9 | Counsel review | **Still open.** Good drafts exist (`docs/pilot-agreement-draft.md`, `docs/driver-consent-bn-draft.md`). The consent draft is now inaccurate (N7). |
| 10 | Human review, then refresh docs | **Still open / partly done.** README refreshed. `docs/risks.md:14`, `docs/pilot-plan.md:11` and `backend/web/README.md:67-68` are stale. |

**Summary:** all 15 baseline bugs are fixed in the code. Of 11 security items, 7 are fixed and 3 partly fixed; S11, human review, is still open. The round was real, careful work. What remains is in places the tests cannot reach: the phone in the driver's pocket, the field, the host and the law.

---

## 1. Verdict up front

- **What it is:** a small, careful FastAPI and Postgres dispatch system. It has a 7-state mission machine, a map console, a Bangla-first driver web app, and a 470-line Android wrapper whose foreground service keeps GPS going with the screen off.
- **Who it is for:** one ambulance fleet under 20 vehicles. No fleet has been named, met or asked.
- **Continue?** Yes, but the next unit of work is not code. It is a host, three phones and one fleet coordinator. The code is ahead of the evidence by weeks.
- **Biggest product gaps now:** no alert reaches a driver whose phone is in his pocket (N1), and free ambulances never show a fresh position, so the map cannot pick the nearest one (N2).
- **My GTM readiness: 16%** (scorecard: 12%).

**Why 16, not 12 or 18.** The 12% cap was set because known defects failed the pilot's own test ("faster or equal to phone/radio"). Those defects (B1-B4, the lat/lng form) are fixed, and I verified them, so 12% now understates the product. The weighted score rises from 31 to 39. I do not go back to the old 18% cap. The work has moved the critical path onto an Android service that has never run on a phone. I found a plausible way for it to run blind (N3). The two gaps above also mean dispatchers will still phone every driver. Safety-critical software with no operator, no device run, no host and no human review stays capped low. Fixing the alert and idle-position gaps and running one device test on a real host would justify the mid-20s.

---

## 2. Code and architecture

**Structure.** It fits the job. The pieces are:
- `backend/app/main.py`: all routes.
- `db.py`: SQLite/Postgres shim and pool.
- `state_machine.py`: pure, 49 lines.
- `sms.py`: 26 lines, stdlib only.
- `bootstrap.py`: CLI.
- Alembic migrations.
- Two front ends with no build step.
- An Android app with no runtime dependencies (no AndroidX, no Play Services).

That is still the right amount of machinery for one fleet.

**Genuinely good, new this round**
- `on_behalf()` derives from `required_role()` (`state_machine.py:47-49`), so there is still one authorization rule. `/meta/transitions?on_behalf=true` and PATCH share it, and a test walks every advertised edge (`test_b3_every_advertised_on_behalf_edge_is_accepted`).
- Double dispatch is fixed twice: an app check, plus partial unique indexes that cannot race (`0006:46-47`). The migration also closes old duplicates and writes an audit row saying why (`0006:31-44`).
- Clock-skew handling is genuinely clever. Age comes from the monotonic clock as `sent_at - ts`, and the stored time is server time (`main.py:503-511`, `PingQueue.kt:72-76`).
- The pairing code is hashed, single use, expires in 10 minutes, dies on revoke, and is rate-limited per code and per client (`main.py:594-630`, `bootstrap.py:37-43`).
- The least-privilege DB role asserts its own result: it checks `has_table_privilege` after granting (`ops/migrate.py:32-34`).
- The restore script drills into a scratch DB by default and asks before a live swap (`ops/restore.sh`).
- `PingQueue` is plain Kotlin with drop rules that mirror the server's, and it is unit-tested.

**Problems**

| # | Issue | Where | Note |
|---|---|---|---|
| C1 | `create_app()` keeps growing: tokens, pairing, SMS dispatch, back-fill, the jump filter and the rate limiter are all closures in one 570-line function. | `main.py:65-636` | Split one cohesive piece out when it is next touched: tokens and pairing (`new_token`, `driver_user`, pairing, revoke) is self-contained. Do not do a framework-style refactor. |
| C2 | Cross-tier constants held equal by comments. | Ping max age: `main.py:65` (300 s), `driver/app.js:41` (300000), `PingQueue.kt:62` (290000). One ping per second: `main.py:65`, `app.js:104`, `PingQueue.kt:64`. Terminal states: `0006:11` "keep equal". | Each "keep equal" is a future silent bug. One test that reads the JS and Kotlin constants and compares them with the server's would catch drift (the house standard already asks for this). |
| C3 | Idempotency keys (a house rule) are still not implemented. | `CODING_STANDARDS.md` vs `main.py:498-532` | Pings tolerate duplicates. A status change has no key, but compare-and-set protects it. Either implement keys or delete the rule. A rule nobody follows teaches agents to ignore the file. |
| C4 | Endpoints with no UI. | `/users` (list, create, revoke), `PATCH /vehicles/{vid}`, `GET /vehicles/{vid}/position`, `POST /me/token/rotate`: neither `app.js` calls them (grep). | Revoking a stolen dispatcher token or taking an ambulance out of service needs curl. Add two buttons, or document the curl lines in the runbook. |
| C5 | Unaudited state changes in an "accountability" product. | Phone change `main.py:426-431`; pairing `:392-405`; active toggle `:384-390`; ack `:494` | See N10. |
| C6 | Tests and production run different dependency versions. | `scripts/check.sh:12` installs `requirements-dev.txt` (unpinned) vs `Dockerfile:4` (hashed lock) | Install the lock in CI, then the dev extras. |

**Standards adherence:** the single role rule, compare-and-set, fail-closed secrets, capped input and escaped DOM writes are all kept. The idempotency rule is not kept (C3). The operator-ownership rule is moot (A10). UNVERIFIED labels are mostly kept; see section 12 for the misses.

---

## 3. Bugs, ranked by severity

| ID | Sev | Status | Bug |
|---|---|---|---|
| N1 | High | Confirmed (traced) | In the Android wrapper, a new mission makes no sound, vibration or notification unless the app is on screen |
| N2 | High | Confirmed (reproduced) | Free vehicles never report, so the map cannot show the nearest free ambulance |
| N3 | High | Suspected (traced; platform behaviour) | Tracking started while the app is hidden can run with no location access and is then trusted as "tracking" |
| N4 | Medium | Confirmed (reproduced) | Five wrong pairing codes from anyone kill every live code; 10 failures lock out every driver behind one IP |
| N5 | Medium | Confirmed (reproduced) | Back-filled step times can predate the mission and run backwards, corrupting response-time data |
| N6 | Medium | Confirmed (traced) | Back-filling an outage mission alerts the driver as a live dispatch, and fails if the vehicle is busy |
| N7 | Medium | Confirmed (traced) | The driver consent draft says tracking happens only "while the app is open"; the wrapper tracks with the screen off |
| N8 | Medium | Confirmed (traced) | The console's QR code pairs the browser, not the wrapper |
| N9 | Low-Med | Confirmed (traced) | Native tracking drops every fix worse than 100 m and never checks for mock locations |
| N10 | Low-Med | Confirmed (reproduced) | Phone (SMS target), pairing and service changes are unaudited; the audit tables have no reader; the API allows a cancel with no reason |
| N11 | Low | Confirmed (reproduced) | `assigned_vehicle_id: ""` is stored and blocks the next mission with a misleading 409 |
| N12 | Low | Confirmed (traced) | "SMS fallback" is sent on every dispatch, its result is invisible, and the header is English only |
| N13 | Low | Confirmed (traced) | The console's ack alarm and elapsed time use the dispatcher PC's clock |
| N14 | Low | Confirmed (traced) | The lock-screen notification shows a raw vehicle UUID; a sideloaded debug build exposes the token |
| N15 | Low (process) | Confirmed | 39 commits unpushed: CI has never run on any of this code, and the Android workflow has never run at all |

**N1. No new-mission alert reaches a pocketed phone in the wrapper.**
- Where:
  - The whole alert is page JavaScript: siren and vibration (`driver/app.js:176-187`) and a Web Notification (`:172-175`), driven by a 15 s `setInterval` poll (`:291`).
  - Android WebView has no Notification API. `backend/web/README.md:109` says "inside the wrapper the native side must notify", but no Kotlin code does. `MainActivity.kt` has no notification code, and `TrackingService` builds only its own low-importance tracking notification (`TrackingService.kt:149-160`), which exists only during a mission.
  - Between missions, no foreground service runs. The app is an ordinary background process, which Android caches and freezes, and which Xiaomi, Oppo and Vivo kill.
- Scenario: the driver finishes a job and puts the phone in his pocket, screen off. The dispatcher sends a new mission. Nothing happens on the phone until he opens the app. The console's 2-minute alarm then says "Phone the driver". So for every mission, the real alert is a phone call, or the SMS if it is paid for and configured. That is the baseline problem in a new place.
- Fix (2-3 days): an "on shift" mode in the wrapper. A foreground service runs from shift start to shift end and polls `/missions/current` every 20-30 s. A new mission posts a high-importance notification with a full-screen intent and an alarm sound. The same service can send idle pings (N2). Cheaper interim fix: make SMS the designed alert. Send it only when no ack arrives within 30-60 s, and include a link that opens the app (N12).

**N2. Free ambulances are invisible on the map.**
- Where:
  - Pings are refused unless the driver has an active mission on that vehicle (`main.py:500-502`). Reproduced: a ping right after cancel gives 403.
  - The map draws a vehicle green only while its last position is under 120 s old (`main.py:32`, `:366`; `dispatcher/app.js:87`).
- Scenario: a free ambulance is fresh for at most 2 minutes after its last mission ends. After that it is a grey "stale" dot at the last hospital, possibly hours old, with no age on the map. The dispatcher's real question, "which free ambulance is nearest?", cannot be answered. Yet the console's own copy, the README ("free, busy and stale vehicles"), the pitch (`pitch/1.html:124`) and the consent draft ("to send the nearest vehicle", `docs/driver-consent-bn-draft.md:22`) all imply it can.
- Fix: accept low-rate idle pings (for example one a minute) from a vehicle's paired driver while he is on shift. Store them under the same retention, and change the consent text to match. Or read positions from the fleet's BRTA-approved hardware tracker, if it has one (section 12). Until then, label free dots with their age and stop saying "free" on the map.

**N3. A hidden page can start a location service that has no location access.** Suspected.
- Where:
  - `load()` runs every 15 s whether the page is visible or not (`driver/app.js:291`). It calls `track()`, then `nativeTrack()`, then `AmbulanceNative.startTracking()` (`:148-158`), with no visibility check.
  - `Bridge.startTracking` does not check that the activity is resumed (`MainActivity.kt:112-130`), although it keeps a `resumed` flag for other reasons (`:33`, `:46-48`).
  - The manifest comment says the service "is only started while the app is on screen" (`AndroidManifest.xml:11`). Nothing enforces that.
  - The service is `START_REDELIVER_INTENT` (`TrackingService.kt:79`), so after an OS kill the system restarts it from the background.
- Scenario (Android 11-13, common on cheap phones in Bangladesh): the app is backgrounded but not frozen, and the battery exemption the wrapper asks for (`MainActivity.kt:154-159`) is granted. A mission arrives.
  - The poll starts the foreground service from the background. With the battery exemption, Android allows the start.
  - Android denies "while-in-use" location to a location service started from the background when the app has no `ACCESS_BACKGROUND_LOCATION` (none is declared). The service runs, shows "Tracking vehicle ...", and receives no fixes.
  - `isTracking()` returns true, and the page's adopt rule (`driver/app.js:154`) then never restarts it, even after the driver opens the app.
  - The dispatcher sees STALE for the whole mission.
- On Android 14+ the start is more likely to throw. The service then stops itself (`TrackingService.kt:66-70`), and the page restarts tracking when the driver returns, so it self-heals.
- Why Suspected: this is documented Android policy, but I could not run it on a device, and the emulator smoke test (`docs/android-wrapper.md:93-100`) always started from the foreground.
- Fix (half a day):
  - Make `startTracking` return false unless `resumed`.
  - In JS, call it only when `document.visibilityState === 'visible'`.
  - In the service, if no fix arrives within 60 s of start, stop with reason `no-fix`, so the page and the console can say so.
  - After a background restart, post "Open the app to resume tracking" instead of running blind.

**N4. Pairing codes have a fleet-wide kill switch.**
- Where:
  - Every wrong code increments the failure count on every live code (`main.py:622`); a code dies after 5 (`:36`, `:617-618`).
  - Ten failures in 10 minutes from one client IP block that IP, even with a good code (`main.py:613-615`).
- Reproduced:
  - I issued codes for drivers A and B, then sent 5 wrong codes. Both correct codes then got 401.
  - After 10 failures, a freshly issued valid code got 429.
- Scenario 1, onboarding day: 15 drivers pair in one room on the office Wi-Fi. Five typos in total kill everyone's code. Ten typos lock the room out for 10 minutes.
- Scenario 2, attack: on mobile data, carrier NAT puts many phones behind one IP. Anyone (an ambulance syndicate is a plausible hostile party, section 12) can keep all pairing dead with about one unauthenticated request a minute.
- The design cap on brute force is sound. The cost is that one person's mistakes hit everyone.
- Fix (half a day): count failures per client and globally, but never kill other codes. Use 8 digits for typed codes. Put a 128-bit secret, not the 6 digits, in the QR. Raise an admin-visible alarm when global failures spike.

**N5. Back-fill can write impossible timelines.**
- Where:
  - `event_time` only has to fall within the last 7 days (`main.py:34`, `:474-476`). It is written straight into `<status>_at` (`:452-453`).
  - It is not compared with the mission's creation time or with earlier steps. The commit `4ceaafa` allows predating on purpose.
- Reproduced:
  - Mission created at 21:34 today.
  - On-behalf EN_ROUTE with `event_time` 3 days earlier: 200.
  - Then AT_SCENE 5 days earlier: 200.
  - Result: `at_scene_at` < `en_route_pickup_at` < `created_at`.
- Why it matters: response-time measurement is the one differentiator this product has (section 12). The pilot's headline metric, "median dispatch-to-acknowledge", is computed from these columns. The console masks this: it clamps negative durations to 0:00 (`app.js:51`).
- Fix (2 h): require each `event_time` to be at or after the previous step's time and not in the future. For outage back-fill, allow the dispatch time itself to be set at creation (see N6).

**N6. Back-filling an outage pretends to be a new dispatch.**
- Where:
  - Back-fill means creating a mission, then making on-behalf moves (`docs/runbook-downtime.md:24`).
  - Creating it sends the driver an SMS "New ambulance mission ..." (`main.py:275-276`, `:228-229`).
  - The driver app sirens and shows "New mission / Accept" (`driver/app.js:144`, `:176-187`) until the dispatcher's on-behalf moves end it.
  - If the vehicle has gone back into service, creation fails with 409 "vehicle or driver already has an active mission" (`main.py:262-264`), because the vehicle is now on a live job. The console only offers free vehicles (`app.js:104-108`).
- Scenario: after a two-hour outage, the dispatcher enters eight paper-log missions. Each driver gets a live-looking dispatch to an old address while he is driving a real patient. Busy vehicles cannot be back-filled at all until they are free.
- Fix (half a day): a "record only" create (`backfill: true`, a real `dispatched_at`, all step times in one request). It sends no SMS, no alert and no busy check, and every step is audited with the reason. Also fix `backend/web/README.md:67-68`, which still says the API refuses times before creation.

**N7. Consent text understates the tracking.**
- Where: `docs/driver-consent-bn-draft.md:14`, `:19` (Bangla) and `:61`, `:64` (English) say position is taken "only while you have a mission and the app is open". The wrapper exists to track with the screen off and the app in the background (`docs/android-wrapper.md:3-5`, `TrackingService.kt:26-29`). N2's fix would add idle tracking on shift.
- Why it matters: consent obtained on a false description is weak consent under any data law, and drivers are the stakeholder most likely to object (risk 6). Fix the text before counsel sees it.

**N8. The QR code pairs the wrong app.**
- Where: the console's QR encodes `https://DOMAIN/driver/#pair=CODE` (`app.js:200`). The wrapper declares only a launcher intent filter (`AndroidManifest.xml:24-27`), with no App Link for that URL.
- Scenario: a driver scans the QR with the camera. Chrome opens and pairs Chrome's copy of the driver app, which loses GPS in the background. Pairing also rotates the token (`main.py:626`), so if he had already paired the wrapper, the wrapper is now signed out. The pairing dialog does not mention the wrapper.
- Fix (2 h): add an App Link (`autoVerify` plus `assetlinks.json`) for `/driver/`, or make the QR carry a custom-scheme link. Tell the driver "open the Ambulance Driver app, then scan", or make the dialog say "type the code in the app".

**N9. Native tracking drops poor fixes and accepts fake ones.**
- Where: `PingQueue.offer` discards any fix with accuracy over 100 m (`PingQueue.kt:26`, `:58`). The web path sends any accuracy up to 100 km (`driver/app.js:120`). `onFix` does not check `Location.isMock()` (API 31+) or `isFromMockProvider()` (`TrackingService.kt:101-107`).
- Scenario 1: in a garage, between tall buildings, or on a cheap GPS chip, fixes sit at 150-500 m. The native path sends nothing, and the dispatcher sees STALE where a coarse dot would have helped.
- Scenario 2: mock-location apps, common for ride-share fraud, pass straight through.
- Fix (1 h): send coarse fixes (the console already draws the accuracy circle) and flag mock fixes in the ping body.

**N10. Accountability gaps.**
- Reproduced: a plain (non-admin) dispatcher changed a driver's phone number, which is the SMS destination for mission addresses: 200, with no audit row (`main.py:426-431`).
- Vehicle-driver pairing (`:392-405`) and taking a vehicle out of service (`:384-390`) are unaudited.
- `auth_audit` and `sms_audit` are written but have no endpoint or UI.
- The API accepts a cancel with no reason (`main.py:469` requires one only for on-behalf moves; reproduced 200).
- Fix (half a day): `auth_audit` rows for these actions, a reason required on cancel, and an admin-only "audit" page listing `auth_audit` and `sms_audit`.

**N11. Empty-string vehicle id.**
- Reproduced: `POST /missions {"assigned_vehicle_id": ""}` returns 201 with `assigned_vehicle_id: ""`. A second such request returns 409 "vehicle or driver already has an active mission", because `""` collides in the unique index.
- Where: `main.py:248-264`. `""` is falsy for the pairing logic but is still inserted.
- The console's `required` select prevents it (`index.html:33`), so this is API-only.
- Related: missions with no vehicle and no driver are allowed, there is no endpoint to assign one later, and the console's alarm says "Phone the driver" for them (`app.js:156-157`).
- Fix (15 min): normalise `""` to None, and require a vehicle unless an explicit `unassigned` flag is set.

**N12. "SMS fallback" is not a fallback.**
- Where: an SMS is sent on every dispatch with a driver (`main.py:275-276`), not when the app fails to acknowledge. The gateway result goes to `sms_audit` (`:230-231`), which nothing reads. The header is English only (`:228`).
- Cost per SMS is roughly ৳0.3-2, unverified; a Bangla address forces unicode, which means multi-part messages. Non-masking sender numbers look like spam.
- Fix: send on create only if no ack arrives within 45 s (a background timer or the daily-task loop), use a Bangla header, and show "SMS sent / failed" on the mission row.

**N13. Console alarm on the PC clock.** `lateAck` and the elapsed column compare `Date.now()` with server timestamps (`app.js:54`, `:138`). A PC clock 3 minutes slow delays the 2-minute alarm by 3 minutes. Fix: take a server time offset from the `Date` response header.

**N14. Small Android leaks.**
- The ongoing notification reads "Tracking vehicle 2f46c412-...", a UUID, on the lock screen (`strings.xml:6`, `TrackingService.kt:155`). Show the registration instead.
- `docs/android-wrapper.md:91` suggests a debug build for real phones. Debug enables WebView remote debugging (`MainActivity.kt:53`), so anyone with the phone and a USB cable can read the token from `localStorage`. Pilot phones need a signed release build.

**N15. Unpushed work.**
- `git log origin/main..HEAD` shows 39 commits. Only `origin/main` exists remotely.
- The backend CI (SQLite and Postgres) has not run on migration 0006 or any new endpoint.
- `.github/workflows/android.yml` has never run.
- Push or merge so CI earns its keep.

---

## 4. Corner cases and failure modes

| Case | What happens now | Status |
|---|---|---|
| Concurrent dispatch of one ambulance | One 201, the other 409. The unique index backs the check. | Confirmed (test + probe) |
| Double tap: "Dispatch" | The second POST gets 409 "already has an active mission" and a toast. Safe. | Confirmed (traced) |
| Double tap: driver step | Confirm dialog; a second PATCH gets 409, the e409 message and a reload. | Confirmed (e2e) |
| Illegal transitions | 409 with `FROM -> TO`. On-behalf moves follow the same graph; cancel after AT_SCENE is still refused. | Confirmed (tests) |
| Driver offline on 2G/3G | 10 s timeout and "Network slow, retrying". Pings queued up to 5 min (web) or 290 s (native), then dropped. Status taps refused offline; the dispatcher records them on behalf. | Confirmed (code, e2e); real network Suspected |
| GPS jitter | Accuracy is stored and drawn. A jump beyond 1 km + accuracies + 70 m/s × dt is refused. A bad accepted fix blocks good ones only until 70 m/s × dt covers the error (self-heals in under a minute for 3 km). | Confirmed (probe + code) |
| Spoofed pings | (0,0) and teleports refused. A plausible fake route or a mock-location app passes (N9). | Confirmed |
| Clock skew (phone) | Accepted; skew reported and shown. +3 h gives 201. | Confirmed (probe) |
| Clock skew (console PC) | Ack alarm early or late (N13). | Confirmed (code) |
| Token expiry mid-mission | Sliding expiry means only after 90 days idle. A revoke mid-mission gives 401 for the driver; the dispatcher finishes the mission on behalf. | Confirmed (probe) |
| Illegal state via on-behalf times | Times can run backwards and predate creation (N5). | Confirmed (probe) |
| DB down | Postgres pool waits up to 30 s, then 500. Caddy's health check flips everything to 503 within about 10 s, including the static console page (Caddy has no other upstream). The driver shell is cached by the service worker. | Confirmed on a laptop by the repo (`docs/deploy.md:86`, `:96`); not re-run |
| Restart mid-mission (server) | State is in the DB. Native pings back off from 2 to 60 s and resume. | Confirmed (code) |
| Android service killed or OEM killer | Redelivered intent, then a background restart: either refused and silent (no page alive to hear it), or running without location (N3). Fixed only when the driver opens the app. The dispatcher sees STALE after 2 min (the designed signal). | Suspected (platform) |
| Doze | The repo's emulator test: with the battery exemption, pings every 5 s; without it, one ping every 15-35 min (`docs/android-wrapper.md:96-98`). The exemption prompt is the right call. | Repo-reported, emulator only |
| Bangla input | Address round-trips. Bangla digits work in phone and pairing code. | Confirmed (probe + code) |
| Phone formats | `01…`, `8801…`, `+8801…`, spaces, hyphens and Bangla digits are normalised. Landlines and short codes are refused. | Confirmed (probe + tests) |
| Pairing brute force | At most 5 guesses per code lifetime globally: sound. Collateral lockout (N4). | Confirmed (probe) |
| Pairing with a stale QR | Code dead after 10 min: "Wrong or expired code, ask for a new one". Fine. | Confirmed (code) |
| Two phones for one driver | The last pairing wins and the other gets 401 and re-pairing. Which one has the wrapper is luck (N8). | Confirmed (code) |
| Mission with no driver | Allowed. Alarm says "phone the driver"; on-behalf audit has `on_behalf_of = NULL`. | Confirmed (probe) |
| Outage back-fill | Driver alerted, busy vehicles 409 (N6). | Confirmed (code) |
| Very long history | Newest first, active view unpaged, pings pruned daily. | Confirmed |

---

## 5. Security and privacy

**Sound**
- Tokens are 256-bit, hashed and sliding. Revoke works for any user and also kills that user's pairing codes (`bootstrap.py:37-43`). Self-rotation cannot undo a revoke (`main.py:542-552`).
- The admin and dispatcher split is real: a plain dispatcher cannot create drivers, mint tokens or revoke (probed 403).
- `/pair` is the only unauthenticated write, and it says so (`main.py:611-612`).
- CSP with no inline script or style. The e2e runs the console under the deployed CSP.
- The app's DB role cannot rewrite audit rows, verified by assertion (`ops/migrate.py:32-34`).
- `FORWARDED_ALLOW_IPS: "*"` is safe only because `app` publishes no port, and the compose file and deploy doc both say so (`docker-compose.yml:45-47`, `docs/deploy.md:31`).
- The Android bridge refuses any `baseUrl` that is not the app's own origin (`MainActivity.kt:118-119`), and every other origin opens outside the WebView (`:61-65`). `allowBackup=false`.

**Gaps**

| # | Issue | Where | Status |
|---|---|---|---|
| P1 | Pairing DoS and carrier-NAT lockout (N4) | `main.py:613-623` | Confirmed |
| P2 | An admin can still act as a driver via "Show token"; nothing shows `auth_audit` | `app.js:212-220`, `main.py:564-566` | Confirmed |
| P3 | Unaudited phone, pairing and service changes; cancel reason optional at the API (N10) | `main.py:384-431`, `:469` | Confirmed |
| P4 | Debug APK with WebView debugging suggested for real phones (N14) | `docs/android-wrapper.md:91`, `MainActivity.kt:53` | Confirmed |
| P5 | Backups unencrypted, on the same disk, with failures only in container logs | `ops/backup.sh:4`, `:12` | Confirmed (documented as owner TODO) |
| P6 | Superuser password in the same `.env` the host operator sees; "append-only audit" holds only against the app role | `docker-compose.yml:33`, `:65` | Confirmed |
| P7 | Mission addresses go to a third-party SMS gateway on every dispatch (N12); the consent draft names it, but the processing agreement has no SMS-specific term beyond a listing | `main.py:229`, `docs/pilot-agreement-draft.md:59` | Confirmed |
| P8 | Unsalted SHA-256 of 6-digit codes is reversible from a DB dump (marked `shortcut:`) | `main.py:619` | Confirmed; acceptable at a 10-minute lifetime |
| P9 | No human review of auth, pairing, the bridge or the service | — | Open |

**Privacy.** Data held: driver names and phones, driver location during missions (and, if N2 is fixed, on shift), and free-text pickup addresses. The console now warns "No patient names or phone numbers here" (`index.html:29`). Pings are kept 90 days, and dumps keep deleted pings for up to 14 days more, which the docs say. The consent draft's scope is wrong (N7).

---

## 6. UI

**Console (1280 px): now a usable control-room screen.**
- Map top left, numbered new-mission form beside it (address, then pickup point, then free vehicle), an active-missions table with elapsed time and an acknowledgement column, a full-width red alarm banner, and a red row for late acks (screenshot `console_1280_alarm`).
- Cancel is a separate red button behind a dialog with a required reason. On-behalf moves are explicit buttons.
- Dhaka time everywhere.
- Problems:
  - No address search: the dispatcher still pans and zooms to find "Mirpur 10, behind the mosque". A geocoder (Barikoi is the local one; Nominatim is weak in Dhaka) would cut the slowest step.
  - Map legend says "free", but free dots are grey "stale" almost always (N2). There is no position age on the map tooltip.
  - English only, with 13-14 px labels (`style.css:16`, `:19`, `:32`).
  - Tables re-render every 5 s, so keyboard focus is lost (the repo says so).
  - No buttons for user management, dispatcher revoke or vehicle out-of-service (C4).
  - At 375 px the console stacks and works for reading only (screenshot `console_375_top`). A toast covers the form. Fine: this is a desk tool.

**Driver app (360 px): still the best part.**
- Black and yellow, big buttons, Bangla first.
- The new-mission card with a huge "গ্রহণ করুন" (Accept) button is exactly right (screenshot `driver_360_new_mission`).
- The 6-digit pairing form with `inputmode="numeric"` replaces the 43-character token. This is the biggest UX gain of the round.
- Problems:
  - The card title is still "নতুন মিশন #298b0feb": a hex id the driver cannot use. Show the pickup and the minutes since dispatch first.
  - No caller or contact line, by design. So the driver cannot call the family, and dispatchers will paste numbers into the address field despite the warning.
  - "Sign out" still sits beside "Refresh". It now asks first, which is good.

**Android:** setup dialogs are bilingual and explain before Android asks. The OEM guide for Xiaomi, Oppo, Vivo and Realme with a dontkillmyapp link is a thoughtful touch. The notification shows a UUID (N14).

---

## 7. UX: real workflows

**Dispatcher, one emergency call, today:**
1. Take the call.
2. Type the landmark.
3. Find it on the map by eye and click (no search).
4. Pick a free vehicle from the dropdown: only free ones with a valid paired driver are enabled. That is good, but the map cannot say which is nearest (N2).
5. Dispatch.
6. Wait. On the wrapper with the screen off, nothing reaches the driver (N1). The SMS goes if it is configured.
7. At 2 minutes the banner and beep say "phone the driver". In practice the dispatcher phones at step 5.

That is 5 actions, one fewer app and no lat/lng typing: a real improvement over 10+ actions. But the pilot's question "faster or equal to phone/radio?" will be answered "equal, plus a phone call", because the call is still needed. The product's value in the pilot will be the record, not the speed. Say that in the pitch and the success criteria.

**Driver:**
1. Pair once with 6 digits, or a QR that goes to the wrong app (N8).
2. Per mission: Accept, then 4 steps each with a confirm: 9 taps.
3. While moving, he should not touch the phone (`docs/pilot-plan.md:58`). The dispatcher records the steps he says by phone, and the audit shows "on behalf".

That is the honest flow. It also means the per-step times in the data are the dispatcher's typing times, not the events, unless the dispatcher sets "When it happened" (and N5 lets those run backwards).

**Onboarding 15 drivers:**
1. An admin creates each driver; the console immediately shows a code and QR (`app.js:297-307`).
2. The driver must first install a sideloaded APK: unknown-sources prompts, Play Protect warnings, then location, notification, battery and OEM dialogs.
3. Typos kill everyone's codes (N4).

Budget a supervised half day, issue codes one driver at a time, and do not run it on a shared Wi-Fi.

**When things go wrong:**
- Cancelled: the driver sees "Cancelled by dispatcher" for 10 minutes. Good.
- Phone dead mid-transport: the dispatcher closes the mission on behalf. Good.
- Clock wrong: a banner tells the driver, and tracking still works. Good.
- Service killed by the OEM: silent until he opens the app. The dispatcher sees STALE (N3).
- System down: the runbook is clear. The back-fill step alerts drivers and fails for busy vehicles (N6).

---

## 8. Accessibility and performance

**Performance on low-end phones: good.**
- The driver shell is about 25 KB (app.js 22.7 KB, 8.2 KB gzipped).
- The service worker caches the shell and never caches API responses (`sw.js:1-12`).
- Polling: 2 requests every 15 s (`/me`, `/missions/current`); transitions are fetched once. That roughly halves the baseline traffic.

**Pings:**
- Web: every 5 s during a mission.
- Native: at least 5 s apart, and if stationary, at most every 10 s (`PingQueue.kt:24-35`).
- Each ping is about 1 KB with headers and TLS, so about 0.5-0.7 MB per mission-hour (estimate). Fine on 2G volume; latency is the issue, and the 10-15 s timeouts are right.

**Battery:**
- GPS and network providers run at a 5 s minimum with a partial wake lock during missions (`TrackingService.kt:55-56`, `:95-97`). This is acceptable for mission-length use.
- An on-shift mode (N1/N2) must drop to a much lower rate when idle, or it will drain a cheap phone in a 12-hour shift.

**Console:**
- Leaflet is 147 KB (43 KB gzipped) plus a 57 KB QR library, loaded once.
- Three polls every 5 s. For 20 vehicles and about 5 active missions, that is about 15 KB per poll before compression, roughly 50 MB a day gzipped (estimate, not measured).
- OSM's public tile servers are fine for a couple of consoles. The repo notes the usage policy.

**Accessibility:**
- Driver app: `lang` switches with the toggle, an `aria-live` status region, focus outlines, 56-72 px targets, and a siren plus vibration, not colour alone.
- Console: `role=alert` banner and toasts, table caption, the map labelled and keyboard-pannable, "NOT ACKNOWLEDGED" in text as well as red.
- Console problems: 13-14 px labels, focus lost every 5 s, English only.
- Untested everywhere: TalkBack, large font, and Bangla rendering in old WebViews (minSdk 26 means Android 8 WebViews, which are updatable but often stale).

---

## 9. Testing and verification

**What the tests prove** (I ran all of them):
- 168 pytest on SQLite, 1 skipped (the Postgres-only migration race).
- The state machine and the on-behalf edges match the API.
- Double dispatch has one winner under concurrency.
- Skewed clocks are accepted.
- Pairing works, expires, and dies on revoke and on bad tries.
- Phones are normalised.
- Retention, healthz, docs-hidden and fail-closed DB path behave.
- Create and audit are atomic.
- Responses match `openapi.yaml`.
- 115 e2e checks in headless Chromium against the real server: the console under the deployed CSP, pairing, the alert and Accept, timeouts, offline queue, skew, 401/409/429 paths, and a fake `window.AmbulanceNative` contract.
- 9 JVM unit tests of `PingQueue` (sampling, drop rules, JSON digits).

**What they do not prove**

| Gap | Why it matters |
|---|---|
| `MainActivity` and `TrackingService` have no automated tests; one manual emulator run (`docs/android-wrapper.md:93-100`). | The wrapper is now the critical path for "live positions". N3 lives here. |
| Background start, OS kill and restart, OEM killers, real Doze, real GPS. | The repo says so. Only a device test answers it. |
| A new mission while the app is backgrounded. | The e2e stubs alerts on a visible page. N1 is invisible to it. |
| Pairing collateral damage (N4). | The test asserts the code dies (`test_tokens.py:204-213`) but not that it kills other drivers' codes. |
| Ordering of back-filled times (N5). | The test asserts predating is allowed (`test_dispatch_loop.py:78-81`), so it locks in half the bug. |
| The least-privilege role is not used in CI; tests connect as superuser. | A future migration whose table the app must UPDATE or DELETE would pass CI and fail in compose. |
| e2e is still not in `check.sh` or CI. | 115 checks run only when someone remembers. |
| None of this branch has run in CI (N15). | Postgres has not run migration 0006 or the new queries. |
| SMS only against a fake gateway, with the success code assumed to be 202. | Check one real send before relying on it. |
| Compose, Caddy, backups and restore: one manual laptop run, recorded in prose. | Good evidence for a first pass; not repeatable. |

---

## 10. Deploy and operations

| Item | State |
|---|---|
| Host | None. Compose ran end to end on a laptop twice on 2026-10-14 (`docs/deploy.md:63-98`). No real DNS or certificate, no reboot test. |
| Build | Reproducible image from the hashed lock. Images untagged; rollback means checking out the old commit and restoring the pre-update dump (`docs/deploy.md:23`), losing data written since. Acceptable for a pilot; write it into the agreement. |
| Health | `/healthz` with a real table read; compose healthcheck; Caddy active health check. Nothing restarts an unhealthy app (documented). |
| Backups | Nightly `pg_dump`, 14 kept, same disk, unencrypted, failures only in logs. The restore drill and live restore were exercised on the laptop. Offsite copy is an owner TODO. |
| Monitoring and alerting | None. No uptime check, no error tracking, no alert on backup failure. |
| Release pipeline | Backend CI exists but has not run on this branch. Android CI builds debug only. No release signing, no versioning beyond `0.1.0`, no distribution channel. |
| On-call | The owner alone. For an advisory, "phone first" tool this is tolerable only with stated pilot hours and a phone number in the runbook. |
| Store compliance | Sideloading for the pilot avoids Play review. A Play release would need the foreground-service location declaration and a justification for `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`, which Play restricts. Google's developer-verification requirement for sideloaded apps (announced 2025: some countries from September 2026, wider rollout after) may reach Bangladesh during a pilot; check before choosing sideloading as the long-term channel. |

---

## 11. Legal and compliance (Bangladesh, plus stores)

I am not a lawyer. This lists what counsel must check.

- **Data protection law has moved again.**
  - The repo names the Personal Data Protection Ordinance 2025 and asks whether the 2026 parliament ratified it (`docs/pilot-plan.md:29-31`). Good question.
  - Public trackers report a Personal Data Protection (Amendment) Ordinance 2026 (Ordinance No. 23, February 2026). It reportedly requires at least one synchronised real-time copy inside Bangladesh for "restricted" data and for critical information infrastructure, and adds turnover-based fines.
  - Compliance sites describe a Personal Data Protection Act 2026 enacted around April 2026, with parts delayed to about May 2027.
  - I found no primary source for the Act. Treat it as UNVERIFIED and give counsel both references. The residency rule bears directly on question 3, hosting and backups outside Bangladesh. ([Digital Policy Alert](https://digitalpolicyalert.org/event/38601-president-implemented-personal-data-protection-amendment-ordinance-2026-ordinance-no-23-of-2026), [ConsentStack](https://www.consentstack.io/regulations/bd-pdpo), [TBS](https://www.tbsnews.net/node/1416106))
- **Consent:** the draft is a good start (Bangla first, plain language, the SMS processor named), but it misstates when location is taken (N7). If on-shift tracking is added, consent must cover it explicitly, and so must the "no discipline unless agreed" clause.
- **Pilot agreement draft:** covers the right terms: advisory only, operator responsible, liability cap, incident reporting, controller and processor roles, SMS provider. Counsel should add that SMS delivery and rollback data loss are not guaranteed (already partly in `docs/pilot-agreement-draft.md:26`).
- **Ambulance regulation:** unchanged since the baseline. There is no comprehensive ambulance policy. BRTA registers vehicles, and the High Court's 2018 EMS guidelines stand.
- **BRTA GPS mandate:**
  - In force since 1 August 2026 for public-transport vehicles: registration and fitness renewals need a working tracker from one of 26 authorised providers, Grameenphone and Obhai among them.
  - Reports do not mention ambulances, so whether they are covered is still unconfirmed. Ask BRTA once in writing.
  - If ambulances are covered, every pilot vehicle carries a tracker, and reading its feed beats phone GPS for idle positions (N2). ([UNB](https://unb.com.bd/category/Special/smart-tracking-for-safer-roads-bangladesh-rolls-out-gps-plan-amid-rising-accidents/184007), [Jago News](https://www.jagonews24.com/en/national/news/94795), [Bonik Barta](https://en.bonikbarta.com/bangladesh/brQvjM00bCIKBfPX))
- **Employment:** location tracking of employed drivers, and its use in discipline, is the predictable dispute. Get the clause signed in Bangla.
- **SMS:** BTRC sender-ID rules apply to masked senders. Non-masked numbers work but look like spam.
- **Stores:** see section 10.

---

## 12. Market, demand and marketability

**Who pays.** This is unchanged from the baseline, and still unvalidated: zero interviews, zero LOIs, zero conversations recorded.

| Candidate | Likelihood | Note |
|---|---|---|
| Private hospital fleets | Medium | The pain is real. The best-run ones (Ad-din, 61 ambulances with trackers and a control room) already have tracking. New hospital apps bundle "request an ambulance" (Bangladesh Specialized Hospital's app, Oct 2025). |
| NGO and charity fleets | Medium for a free pilot | Donors value a mission trail and response-time data. This is the honest wedge. |
| App-based services (URAL EMS) | Low | Competitors with their own app and call centre. ([Prothom Alo](https://en.prothomalo.com/science-technology/App-launched-for-ambulance-services)) |
| District administrations (Swapnojatra, Lakshmipur) | Low-medium | Public precedent exists; slow procurement; a free open-source pilot can sidestep it. ([Prothom Alo](https://en.prothomalo.com/amp/story/bangladesh/good-day-bangladesh/low-cost-app-for-ambulance-service)) |
| 999 | Very low near-term | 999 is police-run (450 staff, 100 lines). It does not dispatch ambulances; it contacts providers, and fares are set by them. It is a referral layer, not a buyer. ([Dhaka Tribune](https://www.dhakatribune.com/bangladesh/government-affairs/410362/fake-unnecessary-calls-delay-999-emergency)) |
| Hospital-gate syndicates | Hostile | Transparency threatens margins. They are relevant to the pairing DoS (N4) as a plausible adversary. |

**Alternatives the operator already has:** phone and WhatsApp groups (free, instant); BRTA-authorised hardware trackers (৳400-600 per vehicle per month, works with the phone off, no driver action); in-house booking apps.

**Why switch.**
- Not for positions: a hardware tracker does that better, and this product cannot even show free vehicles (N2).
- Not for speed: the dispatcher still phones (N1).
- The one real differentiator is the mission record: who was sent, when he accepted, when he arrived, with on-behalf entries and reasons. From that come dispatch-to-acknowledge and call-to-scene times, which donors, hospital management and regulators want.
- That is why N5, backwards back-fill times, matters more than its size suggests.
- Position the product as "response-time accountability for a fleet", and plan to read positions from the trackers fleets will increasingly carry.

**Pricing.** Apache 2.0 code, so no licence revenue. A hosted service at ৳300-500 per vehicle per month for 20 vehicles brings ৳6,000-10,000 a month (about US$50-80). That covers a VM and SMS, not a person on call. This is grant-funded or NGO-partnered, or a feature for a tracker vendor (one of the 26 VTS providers could resell a "mission layer"). The last option is the most realistic paid route and is worth one conversation.

**Distribution.** One introduction to one fleet, which is exactly what the pitch asks for. The pitch's ask is still its best slide.

**Claims vs reality**

| Claim | Where | Reality |
|---|---|---|
| "Vehicles on a map ... free, busy or stale" | `pitch/1.html:124`, `README.md:11` | Free vehicles are stale within 2 minutes of their last mission (N2). |
| "The driver app alerts on a new mission (sound, vibration, notification)" | `README.md:11` | Only while the page is on screen. None in the wrapper's background (N1). |
| "Token control ... automatic 90-day expiry" | `pitch/1.html:128` | 90 days after last use (sliding). |
| "Driver app (PWA)" | `pitch/1.html:125` | The pilot path is the Android wrapper. The pitch does not mention that drivers must sideload an APK. |
| Back-fill "cannot carry earlier real times" | `backend/web/README.md:67-68` | Stale: the code allows 7 days before creation (`main.py:34`). |
| Consent: "only while ... the app is open" | `docs/driver-consent-bn-draft.md:19`, `:64` | False with the wrapper (N7). |
| "Background GPS is expected to stop" (as a still-open risk) | `docs/pilot-plan.md:11` | Stale: the wrapper addresses it, pending a device test. |
| Risk 8: "in-process rate limiter, single-request lock, tokens without expiry/rotation" | `docs/risks.md:14` | All fixed long ago. Risks 2-3 (signals) still rank above real pilot risks. |
| Contact line | `pitch/1.html:59` | Still "OWNER TODO". |

Otherwise the claims discipline is good. UNVERIFIED appears where it should, the "Honest status" slide is honest, and the README's "What does not exist" list is accurate.

---

## 13. GTM % breakdown

| Dimension (weight) | Mine | Scorecard | One line |
|---|---|---|---|
| Product works (25) | 4 | 3 | The dispatch loop now works on a laptop and the wrapper on an emulator. No alert reaches a pocketed phone, the map cannot show free vehicles, and it has never run on a phone. |
| Quality and verification (15) | 5 | 5 | 168 + 115 + 9 tests, all green and re-run by me. The riskiest code (Android service, bridge) has no automated test, e2e is not in CI, and CI has not run on this branch. |
| Security and privacy (15) | 6 | 5 | Headers, admin split, least-privilege role, pairing codes, retention. Minus the pairing DoS, unaudited admin actions, a debug-build risk and no human review. |
| Legal and compliance (10) | 2 | 1 | Counsel-ready drafts and named questions. Nothing reviewed, the consent text is wrong on scope, and the 2026 amendment is not reflected. |
| Market validation (15) | 1 | 1 | Zero interviews, zero LOIs. |
| Deploy and operations (10) | 3 | 1 | Compose stack, healthz, backups and a restore drill exercised on a laptop. No host, offsite copy or alerting. |
| Claims honesty (10) | 6 | 5 | README and pitch largely honest. Stale web README, risks and pilot plan; "free" vehicles; consent scope; contact placeholder. |

**Weighted:** 25(0.4) + 15(0.5) + 15(0.6) + 10(0.2) + 15(0.1) + 10(0.3) + 10(0.6) = 10 + 7.5 + 9 + 2 + 1.5 + 3 + 6 = **39**.

**Cap: 16.** Safety-critical dispatch software with no operator, no device run, no host and no human review. The critical path is an unverified Android service with a plausible blind-tracking failure (N3), and drivers must still be phoned for every mission (N1). **Final: 16%.**

**Where I disagree with `judge.md` and the scorecard**
- `judge.md` stops at Update 13 (before the baseline critique). It does not describe this round at all, and its "18% unchanged" reasoning predates both the dispatch-loop defects and their fixes. It needs an update entry; I did not write one.
- The scorecard's 12% is now too low. Its stated cap reason ("known dispatch-loop defects fail its own pilot criterion") names defects that are fixed and verified. The other cap reasons still hold.
- Scorecard Deploy/ops 1 undercounts: a compose stack with a least-privilege role, health checks and an exercised restore drill is worth 3, even on a laptop.
- The scorecard's Product score treats "real phones" as a test still to run. I now expect that test to surface specific failures I can name (N1, N3, N8, N9). Plan fixes for them before the test, not after.
- Not a disagreement, a warning: the round's commits are all local. A score that counts CI as a strength should note that CI has not seen this code.

---

## 14. What to cut or stop doing

- **Stop polishing the web stack.** Two rounds of excellent console and backend work have moved every remaining risk to the phone, the field and the host. One more agent round on the console has low value.
- **Stop presenting the browser PWA as a driver option for the pilot.** Keep the code as a fallback, but onboard drivers only on the wrapper, and fix the QR (N8) so it cannot steer them to Chrome.
- **Cut "Show token"** (`app.js:212-220`) and the raw-token login in the driver app (`driver/app.js:255-257`). Pairing codes cover both, and the raw token is the S2/S3 hole.
- **Cut signal risks 2-3 from the top-10 risks** and move them under FUTURE. They crowd out real pilot risks (driver alerting, device behaviour, onboarding).
- **Cut the idempotency rule from `CODING_STANDARDS.md`, or implement it.** A rule nobody follows weakens the rest.
- **Stop long-lived local integration branches.** Push or merge each round so CI runs.
- **Do not add Play Services or FCM** to solve N1. A shift-long foreground service plus SMS fits the no-dependency design and works on phones without Google services.

---

## 15. Top 10 next actions (ordered by value)

| # | Action | Effort | Who |
|---|---|---|---|
| 1 | Sit with 3 fleet coordinators (a private hospital, an NGO such as AMI, an app operator). Watch real calls. Ask whether a response-time record is worth an app on the drivers' phones. Record the decision on this project versus traffic lights. | 1-2 weeks elapsed | Owner |
| 2 | Push or merge `oct14-int` so backend and Android CI run. Stand up one HTTPS host (staging is enough). Add an external uptime check to the owner's phone and an offsite copy of the nightly dump. | 1 day | Owner (account, DNS) + agent |
| 3 | Fix N3 before any device test: refuse `startTracking` unless the activity is resumed, call it only when visible, and stop with `no-fix` after 60 s without a fix. Also send coarse fixes and flag mock locations (N9). | Half a day | Agent |
| 4 | Device test on 3 cheap Androids (Redmi, Realme, Vivo or Oppo) against the host. Cover screen off, Navigate to Maps, a mission arriving while backgrounded, an OEM kill mid-mission, Doze, 2G, 30+ minutes. Write down what stops. | 1-2 days | Owner |
| 5 | "On shift" mode in the wrapper: a shift-long foreground service that polls for missions (native high-priority notification with alarm, fixing N1) and sends low-rate idle pings (fixing N2). Server accepts idle pings from the paired driver. Update the consent text first (N7). | 2-3 days | Agent; owner approves consent scope |
| 6 | Pairing redesign (N4): no collateral code kills, 8-digit typed codes, a long secret in the QR, an App Link so the QR opens the wrapper (N8), and an admin alarm on failure spikes. | Half a day | Agent |
| 7 | Back-fill done right (N5, N6): a record-only create with a real dispatch time and all step times; monotonic time checks; no SMS or alert; no busy conflict. Fix the stale README line. | Half to 1 day | Agent |
| 8 | Accountability and SMS (N10, N12): audit phone, pairing and service changes; require a cancel reason; an admin audit page for `auth_audit` and `sms_audit`; SMS only when no ack arrives in 45 s, with a Bangla header. Add address search (Barikoi) to the console. | 1-2 days | Agent |
| 9 | Counsel review with the corrected consent text and the 2026 amendment and Act references. Cover hosting and backup location (residency), consent wording, retention, the SMS processor and the pilot agreement. Ask BRTA in writing whether ambulances fall under the GPS mandate. | 1-2 weeks elapsed, paid | Owner |
| 10 | Human review by one experienced engineer of auth, pairing, the JS bridge and the service. Then release signing, a sideload install guide in Bangla, and a refresh of `risks.md`, `pilot-plan.md:11`, the pitch's contact line and the expiry wording. | 1 day review + 2 h docs | Owner hires; agent edits docs |

---

*Not verified: no real device (all Android findings beyond the code are Suspected or come from the repo's emulator notes); no Postgres run by me (this branch has never run in CI); no Docker or Caddy run by me (I relied on `docs/deploy.md`'s laptop record); no real SMS send; no load test; no WebKit or Firefox. Market and legal facts come from news, tracker and vendor pages found by web search. The 2026 data-protection amendment and Act and the ambulance coverage of the BRTA GPS mandate are not confirmed from primary sources. SMS prices are unverified estimates.*
