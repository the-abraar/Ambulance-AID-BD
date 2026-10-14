# Coding standards (judgement calls a linter cannot enforce)

- Authorize through `required_role()` in `backend/app/state_machine.py` only; it is the single source of who may move a mission to which status. Why: a second role check drifts and lets a role skip a transition (the spec-level hole judge.md found).
- Compare-and-set every state-changing write: `UPDATE ... WHERE id=? AND status=?`, check rowcount, return 409 on conflict. Why: concurrent dispatcher and driver actions otherwise overwrite each other.
- State the auth decision on every endpoint; unauthenticated is a deliberate, commented choice. Why: an open mission endpoint is a signal-hijack path.
- Fail closed on secrets and tokens: no default or placeholder value is accepted outside dev. Why: a shipped placeholder is a working credential.
- Compare owners, not row ids: a driver is checked against the mission's assigned driver, an operator against its own vehicles. Why: ids are shared across users.
- Take idempotency keys from the caller (the driver's queued ping or status), never generate them per request. Why: offline replay would duplicate writes.
- Cap unbounded input explicitly: list `limit`, ping rate, body size, queue length. Why: one client can exhaust the single-worker server.
- Derive mock and fixture names and shapes from the real source (state machine, openapi.yaml); a test must fail on drift. Why: the driver app's state labels (`test_driver_app_labels_every_state`) and the e2e BN label map can silently diverge.
- Mark unmeasured user-facing claims UNVERIFIED (response times, lives saved, legal compliance, Bangladesh data-protection). Why: this is safety-critical and pre-pilot.
- Keep signal preemption out of code until the gates in `docs/roadmap.md` are met. Why: it needs government sign-off and a pentest.
- Put dynamic text into the DOM via `textContent` or `esc()`; `// safe-html:` needs a real reason. Why: API data must never inject markup into the dispatcher console.
