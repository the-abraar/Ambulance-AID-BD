# Owner to-do

Things that need you, newest first. Tick or delete an item when it's done.

## 2026-10-15

- [ ] **Confirm current `main` starts under Docker.** The last run was on 2026-10-14
  (`docs/deploy.md`). Since then only backend code changed; the Dockerfile, dependency lock
  and migrations did not. Start Docker Desktop, then (or ask an agent to) run
  `docker compose up --build -d` with a real `.env` (see `.env.example`), check that
  `/healthz` returns 200 `{"ok":true}`, and `docker compose down`.
