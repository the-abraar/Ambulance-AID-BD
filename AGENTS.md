# AGENTS.md

- Run `scripts/check.sh` before finishing (lint, JS syntax, unsafe HTML, OpenAPI validation, pytest forward and reverse). `--fast` = lint + stray files; it is the pre-commit hook.
- Hooks: `git config core.hooksPath .githooks` is set locally; re-run it in a fresh clone.
- Python 3.11 or 3.12 only (`$PYTHON` overrides). The check venv lives outside the repo at `${CHECK_VENV:-~/.cache/Ambulance-AID-BD-check-venv}`.
- Test deps are in `backend/requirements-dev.txt` (not `requirements.txt`). Playwright is deliberately not in it.
- `AMBULANCE_DB_PATH` selects the SQLite file (default `backend/dev.db`) or a `postgresql://` URL; tests set it themselves. `TEST_DATABASE_URL=postgresql://...` makes pytest run against Postgres (it empties the `public` schema); CI does this.
- `ruff.toml` at the root is explicit on purpose: parent directories carry other ruff configs.
- Browser e2e (37 checks, real server, headless Chromium): read `backend/tests/e2e_browser.py` when changing `backend/web/` (console or driver app). It is not part of `check.sh`; setup is in its docstring. It writes viewport-sized PNGs to gitignored `backend/tests/shots/` plus `INDEX.txt` describing each image.
- API contract: when changing endpoints, edit `docs/api-spec/openapi.yaml`; `backend/tests/test_spec.py` and the check validate it.
- Mission rules: read `backend/app/state_machine.py` when touching statuses or roles.
- Judgement rules for review: `CODING_STANDARDS.md`. Project status and known gaps: `judge.md` (do not edit).
