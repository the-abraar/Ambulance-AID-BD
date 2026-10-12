# Backend (MVP wedge, first piece)

Mission state machine + minimal FastAPI. No signal preemption. Not deployed. SQLite for dev; Postgres supported (set `AMBULANCE_DB_PATH` to a `postgresql://` URL).

    python -m venv .venv && .venv/bin/pip install -r requirements.txt
    .venv/bin/pytest
    .venv/bin/python -m app.bootstrap dispatcher alice     # prints token once; only sha256 stored
    .venv/bin/python -m app.bootstrap driver bob           # prints driver_id + token
    .venv/bin/python -m app.bootstrap vehicle "Op" DHK-1   # prints vehicle_id
    .venv/bin/python -m app

Auth: `Authorization: Bearer <token>`, per-user hashed tokens in DB (`users`). Dispatcher: create/cancel/list/read,
vehicle position. Driver: status moves and pings only for the mission assigned to them (`assigned_driver_id`; pings also
need the matching `assigned_vehicle_id` on a non-terminal mission). Pings: ts within 300 s past / 60 s future, 1/s per
vehicle (in-process limit). Every status change (and creation) is written to `mission_audit`.
Schema is managed by Alembic (`migrations/`), applied automatically at startup. Postgres/PostGIS swap: change TEXT
ids/timestamps to uuid/timestamptz, add geography(Point).

## Doc conflicts (and the choice made)
1. `dispatch-and-citizen-platform.md` diagram models the *vehicle* cycle (AVAILABLE, DECONTAMINATION, no COMPLETED/CANCELLED); `openapi.yaml` MissionStatusUpdate has COMPLETED/CANCELLED and no AVAILABLE/DECONTAMINATION. Chose the OpenAPI enum as mission states; AVAILABLE/DECONTAMINATION are vehicle states, not built.
2. `security-and-anti-abuse.md` uses `DISPATCHED_TO_PATIENT`/`PATIENT_ONBOARD`, which exist nowhere else. Ignored (preemption-only, out of scope).
3. No doc defines where CANCELLED is allowed or the initial state. Chose: new mission starts DISPATCHED (create = dispatch); CANCELLED from DISPATCHED, EN_ROUTE_PICKUP, AT_SCENE only; AT_HOSPITAL -> COMPLETED (diagram's AT_HOSPITAL -> DECONTAMINATION replaced).
4. `/missions/{missionId}/status` in OpenAPI vs `{uuid}` here: same thing. Responses now return `mission_id`; `docs/api-spec/openapi.yaml` was updated to the MVP shapes (create request, Mission, new endpoints) and `tests/test_spec.py` validates responses against it.

## Remaining
Cancel semantics, real auth (token rotation/expiry), PostGIS, shared rate limiter, hospital check-in role.

## Browser e2e
`tests/e2e_browser.py` (not collected by pytest) drives /console and /driver in Chromium against a real uvicorn + fresh SQLite DB:
`python -m venv .e2e && .e2e/bin/pip install -r requirements.txt playwright && .e2e/bin/playwright install chromium && .e2e/bin/python tests/e2e_browser.py [screenshot_dir]`
