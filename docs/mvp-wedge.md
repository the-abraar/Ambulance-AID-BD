# MVP Wedge: Dispatch and Fleet Visibility for One Operator

Source: `judge.md`, blockers 1 and 3. This is the minimal first launch. No signals.

## Scope
- One operator (for example, a single private hospital or NGO fleet). No operator is named or committed yet. A signed pilot LOI comes before code beyond a clickable prototype.
- Dispatch: create, assign and cancel missions. Dispatcher only.
- Fleet visibility: live vehicle positions from the driver Android app over HTTPS.
- Mission state machine as one module, with exhaustive transition tests.

## Build order
1. Mission and vehicle DB on Postgres + PostGIS.
2. Mission state machine module.
3. Driver Android app sending GPS over HTTPS (no MQTT, no mTLS until about 200 vehicles).
4. Web dispatcher console.
5. CI on every push, plus one staging and one prod environment from day one.

## Out of scope for the first launch
- Signal preemption (`/preemption/*`, EVP). Its premise (a controllable TMC API) is unvalidated (`judge.md` blocker 4).
- National CAD integration and the citizen marketplace.

## Security carried over
- Non-guessable mission IDs (UUID/ULID).
- Only the assigned driver's device moves mission states; only the dispatcher creates or cancels.

## Before building
Run discovery interviews (20+ ambulance owners/drivers, 2-3 hospital fleet managers, a 999 supervisor, DMP Traffic) and get the pilot LOI.
