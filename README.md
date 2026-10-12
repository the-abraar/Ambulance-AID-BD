# Ambulance-AID-BD

> Dispatch and fleet visibility for ambulance operators in Bangladesh. Longer-term concepts (signal preemption, 999 integration, a citizen marketplace) are design ideas only and are gated on external prerequisites listed below.

## Honest status (as of 2026-10-12)

**What exists**
- A tested backend (`backend/`, Python/FastAPI): mission state machine, mission create/status/read APIs, vehicle GPS pings, per-user hashed bearer tokens, role checks (dispatcher vs assigned driver), a mission audit log, Alembic migrations. SQLite for dev. Agent-written; test results are agent-reported (see `judge.md`).
- Design documents under `docs/` and an OpenAPI spec (`docs/api-spec/openapi.yaml`).

**What does not exist**
- No signal integration or signal-control code of any kind.
- No partners, no pilot LOI, no government engagement, no legal opinion.
- No field testing, no real vehicles, no real users. No driver app or dispatcher console UI.
- Not deployed. CI has never run on GitHub. Postgres/PostGIS not exercised.
- No measured baseline data. Impact figures in the architecture docs are unsourced estimates (see labels in those docs).

## Current phase: the wedge MVP

A dispatch and live-tracking tool for **one fleet operator** (fewer than 20 vehicles to start), **no signals involved**, advisory only. See [docs/mvp-wedge.md](docs/mvp-wedge.md) and [docs/pilot-plan.md](docs/pilot-plan.md). Top risks: [docs/risks.md](docs/risks.md).

Mission states (single list, matches `backend/app/state_machine.py`):
`DISPATCHED -> EN_ROUTE_PICKUP -> AT_SCENE -> TRANSPORTING_PATIENT -> AT_HOSPITAL -> COMPLETED`, with `CANCELLED` allowed from `DISPATCHED`, `EN_ROUTE_PICKUP` and `AT_SCENE`. The initial state and cancel rules are developer choices that still need confirmation with a real dispatcher.

## FUTURE (not started, not committed)

These are concept designs. Each is gated; none begins until its gate is met.

| Future product | Gate (must be true first) |
| :--- | :--- |
| Emergency vehicle signal preemption (EVP) | (1) Written agreement with the authority that owns the target junctions (UNKNOWN which: DMP, city corporations, or others). (2) Site survey confirms the target signals are networked and API-controllable. This is UNVERIFIED; the repo contains no evidence that Dhaka signals are controllable, and junctions may be manually operated. (3) Simulation, a traffic-engineer-signed safety case, bench test on a real controller. (4) External security review. |
| National 999 / CAD integration | Written agreement with the 999 operating body; legal and data-sharing basis; pilot data as evidence. |
| Citizen booking marketplace | Pilot-proven dispatch, payments and data-protection basis, fare rules verified with the relevant regulator (fare tables in the docs are not verified). No preemption rights attached. |

If signals turn out to be manual, the fallback concept is police-assisted corridor alerts (ETA pushed to a constable), which needs no controller.

## Repository contents

```text
├── README.md
├── judge.md                  # external readiness audit and progress log
├── backend/                  # tested MVP backend (state machine, API, auth, audit, migrations)
├── docs/
│   ├── mvp-wedge.md          # current scope
│   ├── pilot-plan.md         # concrete pilot, data protection, safety
│   ├── risks.md              # top 10 risks
│   ├── roadmap.md            # phased plan with gates
│   ├── security-and-anti-abuse.md
│   ├── api-spec/openapi.yaml
│   └── architecture/         # FUTURE-oriented concept docs (labelled)
└── LICENSE                   # Apache 2.0
```

## Disclaimers

- Architecture docs describe concepts and targets, not facts about Bangladesh infrastructure. Statements not backed by a source are estimates or UNVERIFIED.
- Partner and institution names appearing in docs are examples of who might be approached. None has agreed to anything.
- The `.gov.bd` names in some docs are placeholders; the project has no government ownership.

## License
Apache 2.0, see [LICENSE](LICENSE).
