# Pilot Plan: Dispatch and Fleet Visibility for One Operator

Status: PLAN ONLY. No operator, LOI, budget or date exists. All thresholds below are proposals to be agreed with the operator, not facts. Pricing: UNKNOWN.

## 1. Scope
- One fleet operator (private hospital, NGO or similar; none selected). Fewer than 20 vehicles.
- Functions: dispatcher creates/assigns/cancels missions; assigned driver moves mission state and sends GPS pings; dispatcher sees live positions and mission history.
- Mission states exactly as in `backend/app/state_machine.py`: `DISPATCHED`, `EN_ROUTE_PICKUP`, `AT_SCENE`, `TRANSPORTING_PATIENT`, `AT_HOSPITAL`, `COMPLETED`, `CANCELLED`.
- Out of scope: signals, 999 integration, citizen app, payments, hardware telematics, siren sensing.
- Built and tested in headless browsers only: dispatcher console (`/console/`) and driver web app (`/driver/`). Built and run once on a laptop: the docker compose stack with nightly backups and a restore drill (`docs/deploy.md`).
- Still to do before pilot: run the driver app on real phones in a moving vehicle (background GPS is expected to stop when the screen is off or Maps is open); host the stack on a real server with offsite backups and an uptime alert; counsel review (section 3). Confirm the state machine with the operator's dispatchers first.

## 2. Success criteria (proposed; agree with operator before start)
Measured over a fixed window (proposal: 8 weeks), compared with the operator's own pre-pilot records where they exist (baseline currently UNKNOWN; collect 2 to 4 weeks first).

| Criterion | Proposed threshold |
| :--- | :--- |
| Missions recorded in system vs missions the operator actually ran | at least 90% |
| Missions with complete state trail (no skipped/late updates flagged by dispatcher) | at least 80% |
| Vehicles reporting a ping at least once per active mission | at least 90% of missions |
| Median dispatch-to-acknowledge time | measured and reported; improvement vs baseline is a hypothesis, not a target |
| Dispatcher weekly survey: "system is faster or equal to phone/radio" | majority yes, with a written reason for each no |
| Serious incidents caused by the tool | zero |
| Operator willing to continue after the pilot | yes/no recorded (willingness to pay: UNKNOWN, ask) |

Failure is a valid result and must be published in the pilot report.

## 3. Data protection
Applicable law: the **Personal Data Protection Ordinance 2025**, reported as approved on 9 Oct 2025 and gazetted on 6 Nov 2025, with some sections starting about 18 months after gazetting (about May 2027). How it applies to this pilot is **UNVERIFIED**: no legal opinion has been obtained. Use test data only until counsel has answered these questions in writing:

1. Is the ordinance in force today, and was it ratified by the 2026 parliament? Which of its sections bind this pilot now, and which from about May 2027?
2. Is driver location (GPS pings tied to a named driver and vehicle) personal data under the ordinance? Is any of it sensitive data?
3. Can the pilot be hosted outside Bangladesh, or do the cross-border transfer rules require in-country hosting? Does this include backups?
4. What consent is required from drivers: written or logged, what wording in Bangla, and is consent valid when the employer asks for it? (A draft is in `docs/driver-consent-bn-draft.md`.)
5. Free-text pickup addresses can contain caller names, phone numbers or a medical hint. Does that make them sensitive or health data, and what must the console tell dispatchers?
6. What retention periods are required or allowed for pings, missions, audit logs and backups?
7. Confirm the roles: operator as controller, project owner as processor. What must the processing agreement contain? (A draft is in `docs/pilot-agreement-draft.md`.)
8. What are the breach-notification duties and deadlines, and to whom?
9. How must driver requests to see or delete their data be handled?

What is stored (current backend):
- Users (dispatcher, driver): name/handle, role, hashed token. No plaintext tokens.
- Vehicles and drivers: registration label, operator, driver identity link.
- Missions: id (UUID), assigned driver and vehicle, status, timestamps.
- GPS pings: vehicle position and timestamp, tied to a non-terminal mission.
- Audit log: who changed which mission from which state to which state, and when.
- Not collected in the pilot: patient names, vitals, medical condition, caller phone numbers. Do not add them without a legal opinion and consent text.

Retention (PROPOSAL, not a legal determination): the app deletes GPS pings older than 90 days (`AMBULANCE_PING_RETENTION_DAYS`, default 90). Nightly database dumps are kept 14 days, so a deleted ping can survive in a backup for up to 14 more days. Mission and audit records are kept for the pilot plus a period agreed with the operator and counsel.

Access roles: admin (users and tokens); dispatcher (create, cancel, list, read, vehicle position, status changes on a driver's behalf with a reason); driver (own assigned mission only); host operator (database access, named individuals only, logged). The app's own database role can add audit rows but cannot change or delete them. No public endpoint exposes vehicle positions. Researchers and funders receive aggregated, de-identified data only.

Driver consent: drivers are told in writing (Bangla), before enrolment, what is tracked, when (only during an active mission is the proposal; confirm), who can see it, retention, and that it must not be used for employment discipline unless the operator and drivers agree otherwise. Participation recorded by signed or logged consent. A driver may decline; how that affects employment is the operator's responsibility and must be settled in the pilot agreement.

## 4. Safety
- The tool is advisory only. It never controls, requests or influences traffic signals. No signal code exists and none is added in this pilot.
- It does not give medical advice or triage and does not replace the operator's existing procedures.
- Drivers must not interact with the app while the vehicle is moving; state changes are made when stopped, or the driver says them by phone and the dispatcher records them on the driver's behalf with a reason (the console's "On behalf: <step>" button, with a required reason and an optional "When it happened" time in Dhaka time). The audit log names the dispatcher as the actor and the driver as `on_behalf_of`.
- When the system is down (outage, bad data, no connectivity): operators revert immediately to phone/radio dispatch exactly as before the pilot. The operator keeps the manual procedure and contact list active throughout the pilot. Missions run during an outage are back-filled afterwards by the dispatcher as on-behalf status changes with the reason "outage, paper log". The audit row keeps both the entry time and the real time from the paper log (up to 7 days back).
- Downtime is logged and reported. No uptime target is promised yet (UNKNOWN until measured).
- Incident process: any incident involving a patient or collision pauses the pilot for review.

## 5. Before any signal work starts (all must be true)
1. Pilot success criteria met and report published.
2. Written agreement with the authority that owns the target junctions (UNKNOWN which).
3. Site survey of the target corridor: owner, controller make and firmware, network link, current mode per junction. Target signals verified API-controllable (UNVERIFIED today). If manual, only police-assisted alerts are considered.
4. Legal opinion on signal-control authority and liability.
5. Simulation and a safety case signed by a licensed traffic engineer; one canonical timing table.
6. Bench test on a real controller.
7. External security review and a redesigned, authenticated control path.
8. Named liability and medical/safety sign-off.
