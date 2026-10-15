# Owner to-do

Things that need you, newest first. Tick or delete an item when it's done.

## 2026-10-15

- [x] **Confirm current `main` starts under Docker.** Done 2026-10-15 by an agent (Docker Desktop
  29.5.3, Compose 5.1.4, throwaway `.env` with generated passwords, `DOMAIN=localhost`): on `eea84a7`
  and again with this round's backend change, `migrate` exited 0, `app` turned healthy, and
  `https://localhost/healthz` through Caddy returned 200 `{"ok":true}`; then `docker compose down -v`.
