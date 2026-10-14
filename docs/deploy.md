# Deploy (docker compose)

Status: run end to end on a laptop on 2026-10-14 (results below). Never run on a real host, with a real certificate, or through a reboot.

| Service | Image | Job |
|---|---|---|
| `db` | postgres:16 | Data. Refuses to start with the `.env.example` placeholders or weak passwords. Not published on a host port. |
| `migrate` | app image, one-shot | As the owner (`postgres`): runs migrations, then (re)creates the app's role `ambulance_app` with least privilege (`ops/migrate.py`). |
| `app` | app image (`backend/Dockerfile`, hashed deps from `backend/requirements.lock`) | Connects as `ambulance_app`, not a superuser. Starts only after `migrate` succeeds. Health check: `GET /healthz`. Trusts Caddy's `X-Forwarded-For` (`FORWARDED_ALLOW_IPS`), so per-client limits see the phone's IP. |
| `backup` | postgres:16 | `pg_dump` at start and nightly at 20:00 UTC (02:00 Dhaka) into `./backups/`, newest 14 kept (`ops/backup.sh`). |
| `caddy` | caddy:2 | TLS, security headers, gzip/zstd, 64 KB body cap, upstream health check. Starts after `app` is healthy. |

## First deploy

1. Point DNS for your domain at the host; open ports 80 and 443. HTTPS is required: phone GPS does not work over plain HTTP.
2. `cp .env.example .env`, set `DOMAIN`, and replace both passwords with `openssl rand -hex 32`. Compose refuses to start when a password is empty, still a `change-me` placeholder, shorter than 24 characters, or contains anything but letters and digits (they go into connection URLs unescaped).
3. `docker compose up -d --build`. Order: `db` healthy, then `migrate` runs and exits 0, then `app` and `backup` start, then `caddy` once `app` is healthy.
4. Create the first admin (the token is printed once): `docker compose run --rm app python -m app.bootstrap admin NAME`. Give the dispatch desk dispatch-only accounts (`bootstrap dispatcher NAME`, or `POST /users` as admin). A stolen token: `docker compose run --rm app python -m app.bootstrap revoke USER_ID`.
   - Optional SMS fallback to drivers: set `AMBULANCE_SMS_API_KEY` and `AMBULANCE_SMS_SENDER_ID` in `.env` (see `backend/README.md`), then `docker compose up -d`.
   - Android driver app: set `AMBULANCE_ANDROID_CERT_SHA256` in `.env` to the release key's fingerprint (`docs/android-wrapper.md`), so the console's pairing QR opens the app instead of the browser.
5. Open `https://DOMAIN/console/`; drivers use `https://DOMAIN/driver/`.
6. Run the restore drill below once, now, and write down the date.

Updating: `docker compose restart backup` takes a fresh dump; wait for its `backup ok` line in `docker compose logs backup`, then `git pull && docker compose up -d --build`. `up` re-runs `migrate`, which also gives new tables their grants. Rolling the image back after a new migration fails at `migrate` (Alembic cannot find the newer revision), so roll back by checking out the old commit and restoring that pre-update dump.

## Security settings

- **Headers** (`Caddyfile`): CSP `default-src 'self'`, images also from `data:` and `tile.openstreetmap.org` (and subdomains), `frame-ancestors 'none'`, no inline scripts or styles. Also HSTS (1 year), `nosniff`, `X-Frame-Options DENY`, `Referrer-Policy strict-origin-when-cross-origin` (the OSM tile servers refuse requests without a Referer, so not `no-referrer`), and `Permissions-Policy` allowing geolocation for this site only and denying camera and microphone.
  - New pages must keep scripts and styles in files: no `<script>` blocks, `style=""` attributes or `on...=` handlers. Leaflet's own `element.style` changes are allowed.
  - An in-page QR scanner would need `camera=(self)`.
- **Database roles**: the `postgres` owner password is used only by `migrate` and `backup`. `ambulance_app` can read and write the working tables, but on every `*_audit` table (`mission_audit`, `auth_audit`, `sms_audit`) it can only INSERT and SELECT. It cannot change the schema. `migrate` asserts this every run. A new audit table must be named `*_audit` to get the same protection.
- **Proxy trust**: `FORWARDED_ALLOW_IPS: "*"` is safe only because `app` publishes no port. Never add `ports:` to `app`.
  - To change `APP_DB_PASSWORD`, edit `.env` and run `docker compose up -d`.
  - `POSTGRES_PASSWORD` is applied only when the volume is first created. To change it, run `docker compose exec db psql -U postgres -c "ALTER ROLE postgres PASSWORD 'NEW'"`, then edit `.env` and run `docker compose up -d`.
- `/docs` and `/openapi.json` are served only when `AMBULANCE_DEV=1`. Never set it on a host.

## Health

- `GET /healthz` returns 200 `{"ok": true}`, or 503 when the database is down. On Postgres a dead database answers only after the pool's 30 s timeout. The Docker and Caddy checks time out sooner, and a timeout counts as a failure.
- `docker compose ps` shows the app as `unhealthy` after about 30 s of failures. Nothing restarts it automatically.
- Caddy checks `/healthz` every 10 s. While it fails, every request, including the console page, gets a 503 from Caddy. Dispatchers then switch to [runbook-downtime.md](runbook-downtime.md).

## Backups

- Files: `backups/ambulance-YYYY-MM-DD.dump` (pg_dump custom format). The newest 14 are kept. A same-day rerun replaces that day's file.
- Failures appear only in the logs: `docker compose logs backup | grep FAILED`.
- Deleted GPS pings (90-day retention) can survive in these dumps for up to 14 more days. `docs/pilot-plan.md` section 3 says so.
- **OWNER TODO: offsite copy.** The dumps sit on the same disk as the database, so losing the host loses both. Choose offsite storage (provider, account, region; whether it may be outside Bangladesh is a question for counsel, see `docs/pilot-plan.md` section 3), encrypt the copies, and copy `backups/` there nightly after 20:30 UTC. Until then this is not a backup against host loss.

## Restore drill (monthly, and after any change to `ops/` or `docker-compose.yml`)

1. `ops/restore.sh backups/ambulance-YYYY-MM-DD.dump` (the newest file).
   - It loads the dump into a scratch database `restore_drill`, prints the row count of every table, and drops the scratch database.
   - Live data is untouched.
2. Check the counts are plausible: `missions` and `mission_audit` close to what the console shows, `alembic_version` 1.
3. Write the date and the result in the "Verified" section below.

**Real restore** (data lost or corrupted):
- Run `ops/restore.sh backups/FILE.dump --live` and type `RESTORE` when asked.
- The script first does the drill steps. It then stops `app` and `backup` and renames the live database to `ambulance_before_restore`. The restored copy becomes `ambulance`. `docker compose up -d` then upgrades the schema if needed and re-applies the grants.
- Check the console. Then drop the old copy with the command the script prints.
- On a new host, run `docker compose up -d` once before restoring, so that the `ambulance_app` role exists.

## Verified: 2026-10-14, laptop (Docker Desktop 29.5.3, Compose 5.1.4, postgres:16, caddy:2, `DOMAIN=localhost`)

Results:
- **Refusals.** With the `.env.example` placeholder passwords, `db` printed "refusing to start" and `docker compose up -d` failed with "dependency failed to start". An empty `APP_DB_PASSWORD` stopped compose before any container started.
- **Startup.** The image built. `migrate` exited 0. `app` turned healthy, then `caddy` started.
- **Through Caddy over HTTPS:**
  - `/healthz` returned 200 `{"ok":true}`.
  - The response headers carried all the headers above, with `content-encoding: zstd`.
  - Plain HTTP returned a 308 redirect to HTTPS.
- **Console under the CSP.** `/console/` loaded in headless Chromium. It logged in with a token from `app.bootstrap` and listed missions, vehicles and drivers, with no CSP errors. The driver page loaded too. Its service worker failed only on the local self-signed certificate.
- **Database roles.**
  - Through the app: create vehicle, driver and mission, cancel the mission, rotate a token. All succeeded and wrote to `mission_audit` and `auth_audit`.
  - Probed as `ambulance_app`:
    - Refused with "permission denied" or "must be owner": UPDATE, DELETE and TRUNCATE on the audit tables, UPDATE on `alembic_version`, CREATE TABLE and DROP TABLE.
    - Allowed: SELECT and INSERT on the audit tables.
    - `rolsuper` is false.
- **Restore drill.**
  - The dump (19 KB) restored into `restore_drill` with the expected row counts: 2 users, 1 mission, 2 mission_audit rows, 3 auth_audit rows.
  - A first run showed a gap: the start-up dump ran before `migrate` had created the tables. `backup` now waits for `migrate`.
- **Live restore.**
  - Steps: added vehicle DHA-2, then ran `--live` from an older dump.
  - Afterwards only DHA-1 was left, the app could write again, and audit rows still could not be deleted. `ambulance_before_restore` was kept.
  - Caddy returned 503 for about 2 s until its next health check.
- **Database down.** With `db` stopped, Caddy returned 503 for `/healthz` and `/console/`. Once `db` was back, it returned 200.
- **Cleanup.** `docker compose down -v` removed all containers and volumes.

Second run, same day:
- **Backend.** amb-api's backend (`fix/oct14-amb-api` at `cc57c50`, migration 0006, its hashed `requirements.lock`) with these ops files.
- **Repeated from the first run:** startup, `/healthz`, the CSP console check, the privilege probes (now also on `sms_audit`), the drill and the live restore. All passed.
- **New checks:**
  - `/docs` and `/openapi.json` returned 404.
  - `bootstrap admin` created an admin. Through the API, a dispatcher's on-behalf move with a reason succeeded and added an audit row.
  - `POST /pair` was logged with the host's IP, not Caddy's, so forwarded headers are trusted.
  - With `db` stopped, Caddy returned 503 at once. It returned 200 about 9 s after `db` came back.

The first run used a backend from before amb-api's round, with a stand-in `/healthz` and a `pip freeze` lock, in a scratch copy only. The second run replaces it.

Not checked:
- a real host, DNS, or a Let's Encrypt certificate
- the 20:00 UTC timer firing
- 14-dump rotation over real days
- a reboot
- a phone, the Leaflet map and the QR library (round B)

## Not done

- **OWNER TODO: hosting account and host.** Choose the provider and region; in-country hosting is an open question for counsel.
- **OWNER TODO: uptime alert to the owner's phone.** Use an external check of `https://DOMAIN/healthz`.
- Offsite backups (above), log shipping, error tracking, a staging copy, rate limiting at the proxy, and tagged images for rollback.
