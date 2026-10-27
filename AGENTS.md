# AGENTS.md

- Run `scripts/check.sh` before finishing (lint, JS syntax, unsafe HTML, OpenAPI validation, pytest forward and reverse). `--fast` = lint + stray files; it is the pre-commit hook.
- Hooks: `git config core.hooksPath .githooks` is set locally; re-run it in a fresh clone.
- Python 3.11 or 3.12 only (`$PYTHON` overrides). The check venv lives outside the repo at `${CHECK_VENV:-~/.cache/Ambulance-AID-BD-check-venv}`.
- Test deps are in `backend/requirements-dev.txt` (not `requirements.txt`). Playwright is deliberately not in it.
- `AMBULANCE_DB_PATH` selects the SQLite file or a `postgresql://` URL and is required; only `AMBULANCE_DEV=1` falls back to `backend/dev.db` (and serves `/docs`). Tests set it themselves. `TEST_DATABASE_URL=postgresql://...` makes pytest run against Postgres (it empties the `public` schema); CI does this. The database name must contain "test" unless `TEST_DATABASE_ANY_NAME=1`.
- `ruff.toml` at the root is explicit on purpose: parent directories carry other ruff configs.
- Browser e2e (136 checks in two parts: the console, then the driver app including a fake Android bridge; real server, headless Chromium): read `backend/tests/e2e_browser.py` when changing `backend/web/` (console or driver app). It is not part of `check.sh`; setup is in its docstring. It writes viewport-sized PNGs to gitignored `backend/tests/shots/` plus `INDEX.txt` describing each image.
- API contract: when changing endpoints, edit `docs/api-spec/openapi.yaml`; `backend/tests/test_spec.py` and the check validate it.
- Mission rules: read `backend/app/state_machine.py` when touching statuses or roles.
- Android wrapper (`android/`, Kotlin, no runtime deps): read `docs/android-wrapper.md` before changing it or the driver app's `AmbulanceNative` bridge. Unit tests: `cd android && ./gradlew testDebugUnitTest`.
- Judgement rules for review: `CODING_STANDARDS.md`. Project status and known gaps: `judge.md` (do not edit). Owner to-do: `TODO.md`.
