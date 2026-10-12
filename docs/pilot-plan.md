# Pilot Plan: Dispatch and Fleet Visibility for One Operator

Status: PLAN ONLY. No operator, LOI, budget or date exists. All thresholds below are proposals to be agreed with the operator, not facts. Pricing: UNKNOWN.

## 1. Scope
- One fleet operator (private hospital, NGO or similar; none selected). Fewer than 20 vehicles.
- Functions: dispatcher creates/assigns/cancels missions; assigned driver moves mission state and sends GPS pings; dispatcher sees live positions and mission history.
- Mission states exactly as in `backend/app/state_machine.py`: `DISPATCHED`, `EN_ROUTE_PICKUP`, `AT_SCENE`, `TRANSPORTING_PATIENT`, `AT_HOSPITAL`, `COMPLETED`, `CANCELLED`.
- Out of scope: signals, 999 integration, citizen app, payments, hardware telematics, siren sensing.
- Still to build before pilot: driver Android app, dispatcher console, deployed Postgres-backed environment, backup/restore drill. Confirm state machine with the operator's dispatchers first.

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
Bangladesh data-protection law status: **UNVERIFIED.** No legal opinion has been obtained. Which instruments apply, whether health or location data have special rules, and whether in-country hosting is required are all UNKNOWN. Obtain local counsel's opinion before real data is collected. Until then, use test data only.

What is stored (current backend):
- Users (dispatcher, driver): name/handle, role, hashed token. No plaintext tokens.
- Vehicles and drivers: registration label, operator, driver identity link.
- Missions: id (UUID), assigned driver and vehicle, status, timestamps.
- GPS pings: vehicle position and timestamp, tied to a non-terminal mission.
- Audit log: who changed which mission from which state to which state, and when.
- Not collected in the pilot: patient names, vitals, medical condition, caller phone numbers. Do not add them without a legal opinion and consent text.

Retention (PROPOSAL, not a legal determination): GPS pings 90 days then deleted or reduced to mission-level summaries; mission and audit records kept for the pilot plus a period agreed with the operator and counsel. A deletion job does not yet exist and must be built.

Access roles: dispatcher (create, cancel, list, read, vehicle position); driver (own assigned mission only); operations/admin (database access, named individuals only, logged). No public endpoint exposes vehicle positions. Researchers and funders receive aggregated, de-identified data only.

Driver consent: drivers are told in writing (Bangla), before enrolment, what is tracked, when (only during an active mission is the proposal; confirm), who can see it, retention, and that it must not be used for employment discipline unless the operator and drivers agree otherwise. Participation recorded by signed or logged consent. A driver may decline; how that affects employment is the operator's responsibility and must be settled in the pilot agreement.

## 4. Safety
- The tool is advisory only. It never controls, requests or influences traffic signals. No signal code exists and none is added in this pilot.
- It does not give medical advice or triage and does not replace the operator's existing procedures.
- Drivers must not interact with the app while the vehicle is moving; state changes are made when stopped or by the dispatcher on their behalf.
- When the system is down (outage, bad data, no connectivity): operators revert immediately to phone/radio dispatch exactly as before the pilot. The operator keeps the manual procedure and contact list active throughout the pilot. Missions run during an outage are back-filled afterwards by the dispatcher, flagged as manual.
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
