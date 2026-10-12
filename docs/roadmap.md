# Roadmap (gated, not dated)

No calendar dates are promised. Each phase starts only when the previous phase's exit criteria and the named gates are met. The earlier 24-month plan (200 government vehicles from 2026-11, TMC integration, 2,500 private ambulances) was removed: it assumed procurement, funding, MoUs and signal access that do not exist.

## Where we are
Built: tested backend (mission state machine, mission API, GPS pings, per-user auth, audit log, migrations). Not built or done: driver app, dispatcher console, deployment, any partner, any government engagement, any field test, any signal integration.

## Phase 0: Discovery (CURRENT, in parallel with the backend)
- 20+ interviews (ambulance owners/drivers, 2-3 hospital fleet managers, a 999 supervisor, DMP Traffic). Count so far: 0.
- One signed pilot LOI with one fleet operator (none yet).
- Confirm state machine choices with a real dispatcher.
- Local legal opinion on data protection. Status of Bangladesh data law: UNVERIFIED.
- Exit: a signed pilot partner.

## Phase 1: Wedge MVP and pilot (NEXT)
One operator, fewer than 20 vehicles, dispatch plus visibility only, no signals. Scope in [mvp-wedge.md](mvp-wedge.md), plan and success criteria in [pilot-plan.md](pilot-plan.md).
- Remaining build: driver Android app, dispatcher console, Postgres/PostGIS, deployment, CI actually run, backup/restore drill, offline/phone fallback.
- Output: a measured baseline dataset (response times, utilisation) from the pilot.
- Exit: pilot success criteria met; data-protection and ops basics in place.

## Phase 2: More fleets (FUTURE, gated)
Gate: Phase 1 exit criteria met. Add a small number of further fleets. Test willingness to pay (pricing UNKNOWN).

## FUTURE products (not scheduled)

### A. Signal preemption (EVP)
Gate, all required:
1. Written agreement with the authority that owns the target junctions (UNKNOWN which body).
2. Site survey on one corridor: per junction, owner, controller make and firmware, network link, current mode (manual, fixed-time, actuated). Target signals verified API-controllable. UNVERIFIED today.
3. Traffic simulation and a safety case signed by a licensed traffic engineer. Timing parameters are inconsistent across docs and must be set by that engineer.
4. Bench test on a real controller, then external security review.
5. Pilot, if ever, is one junction, off-peak, police present.
Fallback if signals are manual: police-assisted corridor alerts.

### B. National 999 / CAD integration
Gate: written agreement with the 999 operating body, data-sharing basis, pilot data as evidence.

### C. Citizen booking marketplace
Gate: proven dispatch pilot, payments and consent design, fare rules verified, anti-fraud design. No preemption rights.

### D. Regulatory mandates (telematics tied to licences), multi-city expansion
No mandate exists or is assumed. Depends on regulators' own decisions; nothing here is planned on their behalf.

## Targets
Earlier targets (e.g. a 40% transit-time reduction) were hypotheses with no baseline. They are dropped until the pilot produces measured data.
