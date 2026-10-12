# Launch-Readiness Judgement: Ambulance-AID-BD

> **Current go-to-market score: 18%.** The verdict below is the original 2026-10-12 audit. See *Update 8* at the bottom for the current score, gaps and next steps, and `../GO_TO_MARKET_SCORECARD.md`.

Audited: 2026-10-12, single commit `5360cf1` ("docs: initial architecture..."). Files read: `README.md`, `LICENSE`, `docs/roadmap.md`, `docs/security-and-anti-abuse.md`, `docs/architecture/*.md` (4 files), `docs/api-spec/openapi.yaml`. Total ~1,045 lines, all prose plus one API spec.

## Verdict

**Readiness: about 3%.** This is a concept paper, not a product. There is no code, no tests, no infrastructure, no hardware, no partners and no users. The repo has 9 files: 7 Markdown docs, 1 OpenAPI YAML and a LICENSE. There are no todo files and nothing that runs. The design also bundles three separate national-scale products into one: signal preemption (EVP), a 999 dispatch system (CAD), and a citizen booking marketplace. Each one depends on a government body that has not been engaged: DMP (Dhaka Metropolitan Police), the city corporations, 999 (run by police), BRTA (road transport authority) and DGHS (health directorate). The headline feature, cloud-to-signal preemption, assumes Dhaka has API-controllable automated signals. That is the least validated assumption in the repo, and the docs contradict themselves on it. The spec also has security holes that would let anyone turn signals green. What can realistically launch first is a narrow dispatch and fleet-visibility tool for one fleet operator, with no signals involved. Everything else is years away and needs government sign-off.

---

## Critical blockers (ranked)

### 1. Nothing is built
- **Gap:** There is no backend, driver app, operator console, citizen app, corridor engine, telematics firmware, DB schema, tests, CI, IaC (infrastructure as code) or deploy target.
- **Evidence:** `find . -type f` returns only docs. `README.md:107-120` lists only docs. `openapi.yaml:12-16` points to `api.ambulance-aid.gov.bd`, which does not exist.
- **Why it blocks:** There is nothing to launch.
- **Fix system:** Build only the wedge MVP from blocker 3. Order:
  1. Mission and vehicle DB on Postgres + PostGIS.
  2. Mission state machine as one module, with exhaustive transition tests.
  3. Driver Android app sending GPS over HTTPS. Do not build MQTT or mTLS (mutual TLS) before you have 200 vehicles.
  4. Web dispatcher console.
  5. CI that runs the tests on every push, plus one staging environment and one prod environment from day one.

### 2. Anyone can grant themselves signal preemption (spec-level security hole)
- **Gap:** The mission state controls preemption, but the state endpoint has no auth.
- **Evidence:**
  - `openapi.yaml:61-84`: `PATCH /missions/{missionId}/status` has no `security` block. Anyone who knows or guesses a mission ID (the format is predictable: `MSN-YYYYMMDD-NNNN`, `openapi.yaml:274`) can set it to `TRANSPORTING_PATIENT`. That state unlocks preemption (`dispatch-and-citizen-platform.md:85`).
  - `openapi.yaml:172-175`: "MutualTLS" is modelled as `apiKey` in a header `X-Client-Cert-SHA256`. That is a spoofable header, not mTLS.
  - `openapi.yaml:86-107`: `/preemption/trigger` is a public Bearer-auth endpoint. It should be an internal call, never internet-facing.
  - `PreemptionTriggerRequest` (`openapi.yaml:291-314`) has no `lease_token` field, so the controller-side signature check in `security-and-anti-abuse.md:71` has nothing to verify.
  - The docs say Ed25519 (`security-and-anti-abuse.md:59`), but the sample token header `eyJhbGciOiJFUzI1NiIs` (`traffic-preemption-evp.md:78`) decodes to `{"alg":"ES256"`.
- **Why it blocks:** Signal hijacking is the doc's own "catastrophic" threat (`security-and-anti-abuse.md:13`). Shipping this spec creates it.
- **Fix system:**
  1. Write an authz matrix: role × endpoint × allowed transitions. Only the assigned driver's device moves mission states. Only the dispatcher creates or cancels missions.
  2. Use non-guessable mission IDs (UUIDv4 or ULID).
  3. Remove `/preemption/*` from the public spec. It becomes an internal service-to-TMC (traffic management centre) link over a private network or VPN.
  4. Add `lease_token` to the payload. Pick one algorithm (EdDSA), store keys in an HSM/KMS (hardware security module / key management service), and document key rotation.
  5. Move to OpenAPI 3.1 `mutualTLS`, or terminate mTLS at the gateway and forward the verified identity.
  6. Before any EVP pilot: external pentest plus a threat-model review with DMP.

### 3. No product wedge and no named first customer
- **Gap:** There are three products (EVP, national CAD, citizen marketplace), no MVP cut, and no named buyer, user or pilot partner.
- **Evidence:**
  - `README.md:18-21` (three pillars).
  - `roadmap.md:28-33` puts 200 vehicles across five government fleets in Phase 1, starting 2026-11 (`roadmap.md:9`), which is next month.
  - The OpenAPI `contact` is a "Working Group" that links to a personal GitHub (`openapi.yaml:8-10`).
  - No LOI (letter of intent), MoU or interview notes exist anywhere.
- **Why it blocks:** You cannot launch to "Bangladesh". You launch to one operator who agrees to use it.
- **Fix system:**
  1. Run discovery: 20+ interviews with ambulance owners or drivers, 2-3 private hospital fleet managers, a 999 supervisor and DMP Traffic.
  2. Pick one wedge. Recommended: a dispatch and live-tracking SaaS for one private hospital or NGO fleet, for example Anjuman Mufidul Islam or a private hospital group. It needs no government permission and produces the baseline data (`roadmap.md:40-41`) that every later pitch depends on.
  3. Get a signed pilot LOI before writing code beyond a clickable prototype.

### 4. The core EVP premise is unvalidated: no programmable signals or TMC API to integrate with
- **Gap:** The whole preemption layer assumes networked, controllable signal controllers (NTCIP, SCATS) behind a TMC with an API.
- **Evidence:**
  - `README.md:10` ("as major metropolitan areas ... transition toward automated ... signal systems").
  - `roadmap.md:48` ("newly automated traffic signal controllers").
  - `system-overview.md:77-80` lists the protocols.
  - No document names a controller vendor or model, a controller count, a TMC owner, or confirms that an API exists. Dhaka junctions have historically been controlled by hand by traffic police.
  - Hardware is needed at the pole but is denied: `traffic-preemption-evp.md:17,19` says "None" and "Minimal" capital cost, while `bangladesh-context-and-challenges.md:37-38` requires a LiFePO4 UPS and dual-SIM edge gateways at every pole, and `security-and-anti-abuse.md:71` requires controller firmware that verifies signatures.
- **Why it blocks:** The headline feature has no physical counterpart to talk to, and the cost case rests on a self-contradiction.
- **Fix system:**
  1. Run a site survey with DMP Traffic, DTCA (Dhaka Transport Coordination Authority) and DNCC/DSCC (the two Dhaka city corporations) on the target corridor. Record per junction: who owns it, controller make and firmware, network link, current mode (manual, fixed-time or actuated).
  2. If the answer is "manual", redesign EVP as **police-assisted corridor alerts**: push the ambulance ETA to the traffic constable's phone at each junction. This was already floated in `bangladesh-context-and-challenges.md:27`. It needs no controller.
  3. Only build the NTCIP/SCATS adapter after a controller model is confirmed and a bench unit is available.

### 5. The anti-abuse logic blocks preemption exactly when it is needed, and invites fraud
- **Gap:** The three-factor gate is internally broken.
- **Evidence:**
  - `security-and-anti-abuse.md:24` requires "Moving > 15 km/h". An ambulance stuck in gridlock moves slower than that, which is the exact case preemption exists for (`bangladesh-context-and-challenges.md:12`).
  - `bangladesh-context-and-challenges.md:50` gives private operators green-wave rights as a commercial carrot. That rewards fake bookings: one phone OTP (`security-and-anti-abuse.md:43`) plus a colluding driver who switches on the siren passes Factors 1 and 2.
  - Hospital check-in, the only independent proof, happens after the fact.
- **Why it blocks:** It either never fires in gridlock or is trivially gamed. Either way the doc's own KPI of <1% misuse (`system-overview.md:104`) fails.
- **Fix system:**
  1. Replace the speed gate with route-progress plausibility. Allow stopped-in-queue on the planned path.
  2. Grant preemption only for 999-originated missions or dispatcher-verified ones, never for citizen-app-only bookings.
  3. Confirm hospital receipt (ER staff tap or QR) and auto-flag drivers whose missions don't close at a hospital.
  4. Drop "preemption as commercial incentive".
  5. Build a fraud dashboard that scores drivers by unverified-preemption rate.

### 6. Safety spec contradicts itself and is unproven (life-safety system)
- **Gap:** Clearance timings, hold times and trigger windows disagree across docs. No simulation and no safety case exist.
- **Evidence:**
  - Yellow and all-red minimums: yellow >=3s / all-red >=2s (`system-overview.md:83`); yellow >=4s / all-red >=2.5s (`bangladesh-context-and-challenges.md:26`); yellow 3.5-5s / all-red 2.0-3.5s (`traffic-preemption-evp.md:93-94`).
  - Hold time: 60-90s (`system-overview.md:82`) vs 90s (`traffic-preemption-evp.md:98`).
  - Trigger window: 2-4 min ahead (`system-overview.md:74`) vs ETA<120s (`system-overview.md:40`) vs `tau_flush+30s` (`traffic-preemption-evp.md:44`).
  - A 2-4 min early trigger with a 90s maximum hold means the lease expires before the ambulance arrives.
  - There is no cross-traffic or gridlock-spillback model, even though `roadmap.md:66` admits the risk.
  - There is no handling for grade separation. Dhaka has flyovers, the elevated expressway and metro viaducts, so a vehicle on a flyover above a junction GPS-matches to that junction and triggers it.
- **Why it blocks:** A wrong preemption causes crashes or citywide spillback. No authority will sign off without a safety case.
- **Fix system:**
  1. Keep one canonical `timing-parameters` table, owned by a licensed traffic engineer and referenced by every doc.
  2. Model the corridor in SUMO (traffic simulator) with real counts and evaluate both ambulance gain and cross-street delay.
  3. Use map-matching with road-layer (z-level) awareness and approach-lane geofences.
  4. Write a hazard analysis (FMEA, or IEC 61508-style SIL reasoning) and a formal safety case before any field trial.
  5. Bench-test on a real controller, then trial one junction off-peak with police on site.

### 7. No legal mandate, data-protection or liability basis
- **Gap:** The plan relies on powers the project does not hold and processes sensitive data with no compliance plan.
- **Evidence:**
  - It assumes DMP will issue automated electronic citations (`bangladesh-context-and-challenges.md:51`; `security-and-anti-abuse.md:85`).
  - It assumes BRTA will mandate the telematics (`roadmap.md:79`), with 6 months budgeted for the policy (`roadmap.md:20`).
  - It uses `.gov.bd` domains and an issuer (`openapi.yaml:13`; `security-and-anti-abuse.md:64`) with no government ownership.
  - It handles caller phone numbers, patient condition, vitals and continuous GPS (`openapi.yaml:227-229,265-267`; `dispatch-and-citizen-platform.md:110`) with no retention, consent or access policy.
  - No one is named as liable when preemption contributes to a collision or a triage recommendation is wrong.
- **Why it blocks:** Government partners cannot procure it and private operators can't adopt it. Health and location data without a compliance basis is a legal exposure under Bangladesh's personal-data and cyber-security legislation (verify the current instruments with counsel).
- **Fix system:**
  1. Get a Bangladeshi legal opinion covering signal-control authority under the Road Transport Act 2018, data protection, health-data handling and medical liability.
  2. Write a data inventory and retention policy (e.g. GPS kept 90 days, mission records per health-record rules), consent text in Bangla and in-country hosting if required.
  3. Stop using `.gov.bd` names until a ministry owns the project.
  4. Sign an MoU and data-sharing agreement per partner (999/police, DMP, DGHS).
  5. Name a medical director to sign off triage protocols.

### 8. No business model or funding path
- **Gap:** Nobody is named as the payer.
- **Evidence:** There is no pricing, budget, cost model or funder anywhere. Hardware is costed at $150-300 per vehicle (`traffic-preemption-evp.md:18`), but nobody pays for 200 units, SIM data, 24/7 ops, the 999 console or the TMC work. The license is Apache 2.0, so the IP is not the business. The fare tables shown as "verified pricing" and "municipal regulated" (`dispatch-and-citizen-platform.md:96`; `openapi.yaml:363-368`) do not exist.
- **Why it blocks:** It cannot pay for hardware, operations or a team, and a government pilot needs a costed proposal.
- **Fix system:**
  1. Choose a model per wedge:
     - (a) per-vehicle SaaS fee to hospital or private fleets for dispatch and tracking;
     - (b) booking commission on citizen trips, paid through a mobile-money integration such as bKash or Nagad;
     - (c) grant or development-partner funding for the public EVP pilot (World Bank, ADB, JICA and the Gates Foundation fund Dhaka transport and health work).
  2. Build a unit-economics sheet: hardware, SIM, cloud and support per vehicle per month vs revenue.
  3. Write a costed pilot budget for the Phase 1 proposal.

### 9. All impact numbers are unsourced
- **Gap:** The baselines and targets are asserted, not measured.
- **Evidence:**
  - "Thousands of lives each year" (`README.md:12`).
  - Response time 35-55 min, 3-12 min per junction, 30-50% siren misuse (`system-overview.md:101-104`).
  - ">80% privately owned" (`bangladesh-context-and-challenges.md:46`).
  - The >=40% transit reduction target (`roadmap.md:69`).
  - "5 tiers according to DGHS standards" (`dispatch-and-citizen-platform.md:53`) has no citation.
- **Why it blocks:** Government and funders will reject unsourced numbers. You also can't measure success without a baseline.
- **Fix system:**
  1. Cite a source for every number or label it as an estimate.
  2. Run the Phase 1 baseline data collection as the first deliverable: instrument 20-50 vehicles for 4-8 weeks and publish the dataset.

---

## Major gaps

- **Spec drift on the state machine.** Four different state vocabularies:
  - `README.md:81-84`: `DISPATCHED_TO_PATIENT`, `PATIENT_ONBOARD`, `MISSION_COMPLETED`.
  - `dispatch-and-citizen-platform.md:74-81`: `EN_ROUTE_PICKUP`, `TRANSPORTING_PATIENT`, `DECONTAMINATION`.
  - `openapi.yaml:256-263`: adds `COMPLETED` and `CANCELLED` and omits `AVAILABLE` and `DECONTAMINATION`.
  - `security-and-anti-abuse.md:44` uses the README names.

  Fix: make one enum in the spec the source of truth and generate the docs and code from it.
- **API incompleteness.** Missing:
  - auth/OTP flows; driver login and shift; vehicle registration and certification; hospital endpoints;
  - mission cancel or reassign; fare and payment;
  - error schemas, pagination, idempotency keys, rate limits;
  - websocket or push for live tracking.

  `/missions` POST has no 4xx responses (`openapi.yaml:53-59`).
- **Public location exposure.** `/ambulances/available` (`openapi.yaml:126-164`) has no auth and returns `vehicle_id` with distance. Brokers or syndicates can scrape and triangulate the whole fleet in real time. Fix: return coarse ETA only, add rate limits, require OTP for booking, and never expose stable IDs publicly.
- **No offline or degraded mode.** Dispatch, the driver app and the console all assume continuous 4G. There is no SMS or USSD fallback, no voice-dispatch fallback, no defined cloud-outage behaviour for active missions, and no SLA or RTO/RPO (recovery time and recovery point objectives).
- **No operations model.** There is no 24/7 NOC (network operations centre), on-call rota, incident runbook, monitoring or alerting, or support channel for drivers and dispatchers. A 999-adjacent system needs all of these before go-live.
- **Hardware supply chain undefined.** There is no device vendor or model, no BTRC (telecom regulator) type approval, no installer network, no tamper-seal process and no RMA (returns and repairs) process. The siren current sensor (`roadmap.md:34`) needs per-vehicle-model wiring work.
- **Localization and accessibility.** All UI concepts are in English. Citizens in an emergency need full Bangla, voice/IVR (interactive voice response) for low-literacy callers, and a low-end Android target.
- **Driver incentives ignored.** Syndicates control demand at hospital gates (`bangladesh-context-and-challenges.md:46`). The docs offer no reason drivers would accept platform-set fares beyond a hoped-for mandate. This needs field validation.
- **Roadmap unrealistic.** Hardware for 200 government vehicles starts 2026-11 (`roadmap.md:9`) with no procurement process, funding or MoU. Government procurement alone typically exceeds the 4 months allotted.
- **License wording.** `README.md:119` says "Apache 2.0 / MIT"; `LICENSE` is Apache 2.0. Pick one. Also decide whether a public repo with security details of the signal-control design is appropriate.

---

## Launch path (ordered)

1. **Discovery (weeks 0-6):** 20+ interviews (drivers, fleet owners, hospital ER, 999, DMP). Sign one fleet pilot LOI. Do the junction-ownership and controller survey for one corridor. Get a legal opinion. *Exit: one signed pilot partner, plus a factual answer on whether controllable signals exist.*
2. **Fix the spec (weeks 2-6, in parallel):**
   - one state enum;
   - authz matrix;
   - remove public preemption endpoints;
   - real mTLS;
   - non-guessable IDs;
   - full error and auth flows;
   - source every claim or label it an estimate.
3. **Wedge MVP (months 2-4):** For one private or NGO fleet, about 20-50 vehicles: driver Android app (GPS, mission states, Bangla UI), dispatcher web console, Postgres + PostGIS backend, state machine with tests, CI/CD, staging and prod, monitoring, and a backup/restore drill. No signals and no citizen app.
4. **Pilot and baseline (months 4-6):** Run live with the partner. Measure response times, utilisation and junction wait times. Charge a per-vehicle fee to test willingness to pay. Publish the baseline dataset.
5. **Compliance and ops hardening (months 5-7):** data-protection policy, retention, pentest, 24/7 on-call, incident runbooks, offline/SMS fallback.
6. **Expand fleets, then citizen booking (months 7-12):** add 2-3 more fleets. Launch citizen booking in one zone with OTP and mobile-money payment, with no preemption rights attached.
7. **EVP track (only if step 1 confirmed controllable signals; months 6-18):**
   - SUMO simulation and safety case signed by a traffic engineer;
   - bench-test on the actual controller;
   - one-junction off-peak trial with police present, then a 3-5 junction corridor.

   If signals are manual: pilot police-assisted corridor alerts instead.
8. **Government integration (12+ months):** 999 console integration and BRTA/DGHS policy, using the pilot data as evidence. Keep the `.gov.bd` branding off until a ministry formally owns the system.


---

## Progress log (2026-10-12, Claude session)

**Done:** nothing changed in this session. No edits made.

**Next, in value order:**
1. Fix the spec security holes in `openapi.yaml`: add `security` to `PATCH /missions/{id}/status`, make `/preemption/trigger` internal, add `lease_token` to the request, and reconcile Ed25519 with ES256.
2. Cut the scope to the wedge MVP in blocker 3: dispatch and fleet visibility for one operator, no signals.


### Update 2 (supersedes "nothing changed" above; agent-made, not reviewed by a human)

**Done (YAML parses with Ruby; no OpenAPI linter run):** `openapi.yaml` bumped to 3.1.0. `PATCH /missions/{id}/status` now requires `BearerAuth`. The spoofable header is replaced by a real `mutualTLS` scheme. `/preemption/trigger` and `/release` tagged `Internal-Preemption` with their own server URL. `lease_token` is required on the trigger request. Mission IDs are UUIDs. The sample JWT header now decodes to EdDSA. New `docs/mvp-wedge.md`.

**Still open:** `tmc-link.internal.ambulance-aid.gov.bd` is a made-up placeholder; replace it. No authz matrix or key-rotation doc. Run `npx @redocly/cli lint`. Blocker 1 (nothing built) is untouched.


### Update 4 (agent-made; agents' own reports, not yet independently re-run)

**Done (`pytest` 61 passed in a fresh venv; `.github/workflows/backend.yml` has never run):** `backend/` Python package: pure state machine `app/state_machine.py` with tests for all 49 state pairs and terminal states; FastAPI routes for create, status update and read of missions and for vehicle GPS pings; UUID mission IDs; SQLite dev DB; two bearer tokens (`AMBULANCE_DISPATCHER_TOKEN`: create and cancel; `AMBULANCE_DRIVER_TOKEN`: other status moves and pings). No preemption code.

**Doc conflicts (also in `backend/README.md`):** the architecture diagram (vehicle cycle) and the OpenAPI enum (COMPLETED, CANCELLED) disagree, and the agent used the OpenAPI enum; `security-and-anti-abuse.md` uses `DISPATCHED_TO_PATIENT` and `PATIENT_ONBOARD`, which appear nowhere else, and the agent ignored them; no doc gives an initial state or says where CANCELLED is allowed, so the agent chose DISPATCHED as initial and CANCELLED from DISPATCHED, EN_ROUTE_PICKUP and AT_SCENE only. **Those are the agent's choices; check them with a real dispatcher.**

**Still open:** a driver token can move any mission (not bound to the assigned driver); responses return `id` but the spec says `mission_id`; no vehicle table, position-read endpoint, migrations, PostGIS or real auth; no partner or government engagement.


### Update 5 (agent-made, round 6; agents' own reports unless marked)

**Done (agent run: pytest 69 passed in a fresh venv; spec test validates responses; CI workflow not run on GitHub; no signal-preemption code):** tables `users` (hashed tokens), `vehicles`, `drivers`, `mission_audit`; missions get an assigned driver and vehicle at creation; a driver can move or read only their own mission, and pings need that driver, that vehicle and a non-terminal mission; shared env tokens removed (`python -m app.bootstrap dispatcher|driver|vehicle` prints a token once). `GET /vehicles/{id}/position` and `GET /missions?status=` (dispatcher-only). Responses return `mission_id`; **parts of `openapi.yaml` were rewritten to the MVP shapes** (`MissionCreateRequest`, `Mission` with `additionalProperties: false`, shared `MissionStatus`; `/telemetry/ingest` marked unimplemented), so read the diff before treating it as the target design. Alembic migration `0001` replaces `create_all`. Pings must be within 300 s past or 60 s future, 1 per second per vehicle. Every mission creation and status change is audit-logged.

**Still open:** rate limiter is in-process only; migrations not run on Postgres or PostGIS; CI never run on GitHub; the agent's state-machine choices (initial state DISPATCHED, CANCELLED only from DISPATCHED, EN_ROUTE_PICKUP, AT_SCENE) need checking with a real dispatcher; no partner or government engagement; nothing about signals is built.


### Update 6 (agent-made: independent verification, security review, fixes; agents' own reports unless marked)

**Independent re-run confirmed:** pytest 69 passed (before the fix), `openapi-spec-validator` OK on `openapi.yaml`.

**Security review found (fixed; pytest 71 passed per the agent):** the status UPDATE had no compare-and-set, so a dispatcher CANCEL and a driver advance sent concurrently could leave a cancelled mission overwritten and both audit rows with the same `from_status`; one SQLite connection was shared across threads. Fixes: `advance()` in `app/main.py` updates `WHERE id=? AND status=?`, 409 and rollback if rowcount is not 1, audit row in the same transaction; a request-scoped lock serializes all requests (marked `shortcut:` in the code, so throughput is limited to one request at a time). Review confirmed token hashing, driver-to-mission and driver-to-vehicle binding, ping validation and parameterised SQL are sound.

**Still open:** concurrency fix tested by simulating a stale status only, not real threads; Postgres and PostGIS; CI never run; state-machine assumptions need a dispatcher's confirmation; everything about signals.


### Update 7 (agent-made, priority round; agents' own reports unless marked)

**Done (agent runs: pytest 94 passed; browser e2e `backend/tests/e2e_browser.py` 28 checks against the real backend, Chromium via Playwright; not re-run by me):**
- **API (`app/main.py`):** `GET /me`, `GET /missions/current`, `GET /meta/transitions` (role-aware via one shared `required_role()` in `app/state_machine.py`, also used by PATCH), `GET/POST /vehicles`, `GET/POST /drivers` (driver token shown once), `GET /missions/{id}/audit`. Authorization tests: 401 unauthenticated, 403 for a driver on every dispatcher endpoint, a driver cannot see another driver's mission.
- **Pickup coordinates:** `pickup_lat` and `pickup_lng` (nullable, range-checked, sent together); Alembic migration `0002_pickup_coords.py` with an upgrade-from-0001 test that keeps existing data.
- **Dispatcher console** `backend/web/dispatcher/` (served at `/console`): token in `sessionStorage`, mission list with filter, create form with real lat/lng, role-aware buttons, vehicle list with stale-ping highlight, audit drawer, 5 s polling, error toasts, text inserted via `textContent` (a vehicle named `<b>DHK-1</b>` rendered as literal text).
- **Driver app** `backend/web/driver/` (served at `/driver`): installable web app, GPS ping every 5 s while on a mission, offline ping queue, Bangla and English labels for the 7 real states, Navigate link from numeric lat/lng. `mock_server.py` follows the real state names; a test fails if it drifts.
- **Docs (agent made, did not re-read after editing):** README and roadmap rewritten to state what exists; EVP, 999/CAD and the marketplace labelled FUTURE with named gates; flagged claims labelled UNSOURCED, UNVERIFIED or UNDECIDED or removed; one mission state list in `dispatch-and-citizen-platform.md` section 4 matching `state_machine.py`; new `docs/pilot-plan.md` (data-protection and safety sections, Bangladesh data-law status UNVERIFIED) and `docs/risks.md`.

**e2e covered:** console create vehicle, driver and mission; driver walks to COMPLETED via the app with fake geolocation; a fresh ping at each state; the console reflects each state and offers only allowed buttons; 401 bad token; 409 when the dispatcher cancels while the driver's confirm dialog is open; English toggle; screenshots at 360 px and 1280 px with no layout defects found. **Not covered:** offline queue replay, denied GPS permission, the service worker (blocked in the test), the filter, the audit drawer and the 429 state.

**Still open:** the mission ID on the driver card is the full UUID and wraps at 360 px; real phones and real GPS; Postgres and PostGIS (migrations 0001 and 0002 only on SQLite); in-process rate limiter and request lock (one request at a time); CI never run on GitHub; the state-machine assumptions need a real dispatcher; no partner or government engagement; geolocation needs HTTPS in production; the inline SVG install icon may not satisfy some browsers' install prompt. **No signal-preemption code exists.**


---

## Update 8: go-to-market scoring (2026-10-12)

**Score: 18% (was 3%).** Stage: Wedge software works on a laptop; no operator, no field test.

**Cap:** 18: safety-critical software with no pilot operator, no real-phone or real-GPS test, and no Postgres run.

**Dimension scores (0-10):** Product 5, Quality 7, Security 6, Legal 2, Market 1, Ops 2, Honesty 7. Rubric and the other five projects: `../GO_TO_MARKET_SCORECARD.md`.

**Basis and limits:** my judgement from this file's audit, the agents' reports, and independent re-runs of tests and builds. No real-device, real-user or real-host testing has happened, and nothing is committed. Agent-written code has had no human review. Treat the score as +/- 10 points.

### Gaps and flaws, ranked

1. **No operator, no partner, no government engagement.** The wedge is only useful with a fleet operator who will use it.
2. **Never run on real phones or real GPS.** The browser tests used a fake position in headless Chromium. Offline replay, denied-GPS, the service worker and the 429 path were not covered by the e2e.
3. **SQLite only.** Migrations 0001 and 0002 were never run on Postgres or PostGIS; PostGIS is not used at all yet.
4. **One request at a time.** A lock serializes every request (marked `shortcut:` in code). The rate limiter is in-process only. Both break or limit with more than one worker.
5. **State machine is the agent's choice** where docs conflicted: initial state DISPATCHED; CANCELLED only from DISPATCHED, EN_ROUTE_PICKUP and AT_SCENE. A real dispatcher must confirm.
6. **Token handling is thin:** tokens are shown once at creation and stored hashed, but no rotation, expiry or revocation flow was reported; bootstrap is a command-line script.
7. **Safety and data protection:** Bangladesh location-data law is UNVERIFIED; drivers' consent and retention rules are only drafted in `docs/pilot-plan.md`; no plan has been tested for the system being down (operators must revert to phone or radio).
8. The driver card shows the full UUID, which wraps at 360 px; geolocation needs HTTPS in production; the inline SVG install icon may not satisfy some install prompts. CI workflows have never run on GitHub.
9. The `openapi.yaml` was rewritten to the MVP shapes; the original full design is no longer in the spec. **No signal-preemption code exists and none should be written before the gates in `docs/roadmap.md`.**

### What to do next, in order

1. **You:** find ONE fleet operator (under 20 vehicles) willing to pilot dispatch and visibility only; agree success criteria from `docs/pilot-plan.md`.
2. **You:** run the driver app on 2-3 real Android phones in a moving vehicle with real GPS; show the console to a real dispatcher and have them check the state list and cancel rules.
3. **Code:** move to Postgres (add PostGIS only when a query needs it); replace the request lock with per-request connections and transactions; shared rate limiting; a token revoke and rotate endpoint with tests.
4. **You:** host it with HTTPS (needed for geolocation) and a staging environment; run the GitHub workflow once; get a human review of the auth and audit code.
5. **You:** verify Bangladesh data-protection requirements with counsel; get drivers' written consent text approved.
6. **Code:** cover offline replay, denied GPS and the 429 state in the e2e; shorten the mission ID on the driver card; add a down-time runbook.
7. **Only after a pilot works:** revisit the FUTURE items; signals stay out until the written gates in the roadmap are met.

### Update 9 (2026-10-12, stopped at the 70% usage ceiling)

**Done this round:** retro guardrails (`scripts/check.sh`, pre-commit hook `.githooks/pre-commit`, CI workflow, `AGENTS.md`, `CODING_STANDARDS.md`); orphaned worktrees removed (Suggest.Bike); all work committed and pushed to `origin/main`. Usage mirror `../usage.md` is live (status line writes the 5-hour and 7-day percentages); read it before starting a round.

**I was in the middle of:** nothing half-done. The last action was this log. No uncommitted work remains apart from this file.

**Not verified:** the GitHub CI workflows have never run; the pre-commit hook has never blocked a real commit; no real-device, real-user or real-host testing.
**Next, first:** one fleet operator for a pilot; run the driver app on a real phone with real GPS; see Update 8.

### Update 10 (2026-10-13): code gaps closed

Edited at the user's explicit request (`AGENTS.md` otherwise says not to edit this file). Pushed in `953c5d3` and the commit after it.

**Closed (rewrites the status of Update 8 gaps):**
- Gap 3 (SQLite only): the app and migrations 0001-0004 run on Postgres; pytest passes on Postgres 16 locally (embedded server) and in GitHub CI (101 passed). PostGIS is still not used.
- Gap 4 (one request at a time): the global lock is gone; one connection per request (SQLite WAL, or a Postgres pool). The ping rate limit lives in the `ping_limit` table, so it holds across workers. Concurrency tests cover a status race and a shared rate limit.
- Gap 6 (token handling): `POST /drivers/{id}/token/rotate`, `.../revoke` and `POST /me/token/rotate`; tokens expire after 90 days (`users.token_expires_at`; the migration gives existing users 90 days from migration day). An expired dispatcher token cannot rotate itself: create a new one with `python -m app.bootstrap`.
- Gap 2 (real phones): still open. Offline replay, denied GPS and the 429 message are now covered in headless Chromium (e2e: 34 checks), not on a real phone or real GPS.
- Gap 8: the driver card shows 8 characters of the mission ID. HTTPS, the install icon, and the first GitHub CI run: CI has now run green (including the Postgres step).
- Next-step item 6 is done; `docs/runbook-downtime.md` is a draft nobody has rehearsed.

**Still open, unchanged:** gaps 1, 5, 7 and 9; next steps 1, 2, 4 (HTTPS, human review of auth code), 5, 7. No real operator, device, host or counsel review. Agent-written code has had no human review. The score in Update 8 (18%) should not move on this work alone.
**Shortcuts remaining:** Postgres pool is a fixed 1-10 connections (`app/db.py`); no token expiry warning in the UI; the rate-limit table grows one row per vehicle and is never pruned.
