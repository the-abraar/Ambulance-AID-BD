# Deploy (docker compose)

Status: run end to end on a laptop on 2026-10-14 (results below). Never run on a real host, with a real certificate, or through a reboot.

| Service | Image | Job |
|---|---|---|
| `db` | postgres:16 | Data. Refuses to start with the `.env.example` placeholders or weak passwords. Not published on a host port. |
| `migrate` | app image, one-shot | As the owner (`postgres`): runs migrations, then (re)creates the app's role `ambulance_app` with least privilege (`ops/migrate.py`). |
| `app` | app image (`backend/Dockerfile`, hashed deps from `backend/requirements.lock`) | Connects as `ambulance_app`, not a superuser. Starts only after `migrate` succeeds. Health check: `GET /healthz`. Trusts Caddy's `X-Forwarded-For` (`FORWARDED_ALLOW_IPS`), so per-client limits see the phone's IP. |
| `backup` | postgres:16 | `pg_dump` at start and nightly at 20:00 UTC (02:00 Dhaka), encrypted with `BACKUP_PASSPHRASE`, into `./backups/`, deleted after 14 days (`ops/backup.sh`). Health check: unhealthy when the newest dump is over 26 hours old. |
| `offsite` | rclone/rclone:1.75.2 | Off unless `COMPOSE_PROFILES=offsite`. Copies the encrypted dumps to `BACKUP_OFFSITE` at start and nightly at 20:30 UTC, deletes copies there once they are 13 days old (`ops/offsite.sh`). Health check: unhealthy when the last good copy is over 26 hours old. |
| `caddy` | caddy:2 | TLS, security headers, gzip/zstd, 64 KB body cap, upstream health check. Starts after `app` is healthy. |

Images are pinned by digest (`tag@sha256:...`) in `docker-compose.yml` and `backend/Dockerfile`, so every host runs the same bytes; Dependabot (`.github/dependabot.yml`) opens a PR when a tag moves. To bump by hand: `docker buildx imagetools inspect IMAGE:TAG` prints the new index digest.

## First deploy

1. Point DNS for your domain at the host. Set up the firewall and SSH as in [Host](#host): only ports 22, 80 and 443 open. HTTPS is required: phone GPS does not work over plain HTTP.
2. `cp .env.example .env`, set `DOMAIN`, and replace both passwords and `BACKUP_PASSPHRASE` with `openssl rand -hex 32`. Store `BACKUP_PASSPHRASE` off this host too (a password manager): without it no dump can be restored, and a lost host takes `.env` with it. Compose refuses to start when a password is empty, still a `change-me` placeholder, shorter than 24 characters, or contains anything but letters and digits (they go into connection URLs unescaped).
3. `docker compose up -d --build`. Order: `db` healthy, then `migrate` runs and exits 0, then `app` and `backup` start, then `caddy` once `app` is healthy.
4. Create the first admin (the token is printed once): `docker compose run --rm app python -m app.bootstrap admin NAME`. Give the dispatch desk dispatch-only accounts (`bootstrap dispatcher NAME`, or `POST /users` as admin). A stolen token: `docker compose run --rm app python -m app.bootstrap revoke USER_ID`.
   - Optional SMS fallback to drivers: set `AMBULANCE_SMS_API_KEY` and `AMBULANCE_SMS_SENDER_ID` in `.env` (see `backend/README.md`), then `docker compose up -d`.
   - Android driver app: set `AMBULANCE_ANDROID_CERT_SHA256` in `.env` to the release key's fingerprint (`docs/android-wrapper.md`), so the console's pairing QR opens the app instead of the browser.
5. Open `https://DOMAIN/console/`; drivers use `https://DOMAIN/driver/`.
6. Set up the offsite copy ([Backups](#backups), "Offsite copy") before any real data goes in. Until it runs, the dumps sit on the same disk as the database, so losing the host loses both.
7. Set up the alert ([Health](#health), "Alert"), so a failed night or a dead host reaches your phone.
8. Run the restore drill below once, now, and write down the date.

Updating: `docker compose restart backup` takes a fresh dump; wait for its `backup ok` line in `docker compose logs backup`, then `git pull && docker compose up -d --build`. `up` re-runs `migrate`, which also gives new tables their grants. Rolling the image back after a new migration fails at `migrate` (Alembic cannot find the newer revision), so roll back by checking out the old commit and restoring that pre-update dump.

## Security settings

- **Headers** (`Caddyfile`): CSP `default-src 'self'`, images also from `data:` and `tile.openstreetmap.org` (and subdomains), `frame-ancestors 'none'`, no inline scripts or styles. Also HSTS (1 year), `nosniff`, `X-Frame-Options DENY`, `Referrer-Policy strict-origin-when-cross-origin` (the OSM tile servers refuse requests without a Referer, so not `no-referrer`), and `Permissions-Policy` allowing geolocation for this site only and denying camera and microphone.
  - New pages must keep scripts and styles in files: no `<script>` blocks, `style=""` attributes or `on...=` handlers. Leaflet's own `element.style` changes are allowed.
  - An in-page QR scanner would need `camera=(self)`.
- **Database roles**: the `postgres` owner password is used only by `migrate` and `backup`. `ambulance_app` gets only what the code uses: SELECT and INSERT on every table; UPDATE on `missions`, `drivers`, `vehicles`, `pairing_codes` and `ping_limit`; UPDATE on `users` only for the token columns (`token_hash`, `revoked_at`, `token_expires_at`, never `admin` or `role`); DELETE only on `pairing_codes`, `ping_limit`, `rate_events` and `vehicle_pings`. So every `*_audit` table (`mission_audit`, `auth_audit`, `sms_audit`) is INSERT and SELECT only, and the role cannot change the schema. `migrate` rebuilds these grants and asserts the audit tables and `users.admin`/`users.role` every run. A new table gets SELECT and INSERT only until it is added to the lists in `ops/migrate.py`; a new audit table must be named `*_audit` to be checked.
- **Proxy trust**: `FORWARDED_ALLOW_IPS: "*"` is safe only because `app` publishes no port. Never add `ports:` to `app`.
  - To change `APP_DB_PASSWORD`, edit `.env` and run `docker compose up -d`.
  - `POSTGRES_PASSWORD` is applied only when the volume is first created. To change it, run `docker compose exec db psql -U postgres -c "ALTER ROLE postgres PASSWORD 'NEW'"`, then edit `.env` and run `docker compose up -d`.
- `/docs` and `/openapi.json` are served only when `AMBULANCE_DEV=1`. Never set it on a host.
- **Containers** (`docker-compose.yml`): every service runs with `no-new-privileges`.
  - `app`, `migrate`, `offsite` and `caddy` drop all Linux capabilities. `caddy` gets back only `NET_BIND_SERVICE`, for ports 80 and 443.
  - `app` and `caddy` have a read-only root filesystem with a `tmpfs` for scratch files, plus memory and process limits (`app` 512 MB, `caddy` 256 MB, 200 processes each). Caddy's certificates live in the `caddy_data` volume.
  - `db` and `backup` keep the default capabilities. The postgres entrypoint needs them to set up its data directory and drop to the `postgres` user, and `backup` runs as root because its entrypoint skips that drop.

## Host

Do this before step 1 of the first deploy (Ubuntu commands; adapt for other systems).

- **Docker:** Docker Engine 25 or newer with the Compose plugin (`docker version`, `docker compose version`). The health checks use `start_interval`, which older engines reject.

- **Firewall:** only SSH, HTTP and HTTPS.
  - `ufw default deny incoming && ufw default allow outgoing && ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw enable`
  - Docker writes its own iptables rules for published ports and bypasses UFW. That is why only `caddy` publishes ports. Never add `ports:` to `db` or `app`.
- **SSH:** keys only, no root login.
  - Copy your key first (`ssh-copy-id USER@HOST`) and check that a key login works.
  - Then set `PasswordAuthentication no`, `KbdInteractiveAuthentication no` and `PermitRootLogin no` in a file under `/etc/ssh/sshd_config.d/`, and run `systemctl reload ssh`.
  - Keep the current session open until a new key login works.
- **Updates:** `apt install unattended-upgrades` for security patches. Plan a reboot for kernel updates; every service restarts on its own (`restart: unless-stopped`).

## Logs

- Every service logs to Docker's `json-file` driver with rotation: at most 5 files of 10 MB per container (the `x-defaults` anchor at the top of `docker-compose.yml`, applied with `<<: *defaults`). A new service must include `<<: *defaults` too.
- Without rotation the logs would grow until the disk fills, and a full disk also stops the backups.
- The app's access log records each request's client address, method, path and status, not request bodies, so GPS positions do not reach the logs. Rotation keeps these lines for days, not months.
- Read them with `docker compose logs SERVICE`.

## Health

- `GET /healthz` returns 200 `{"ok": true}`, or 503 when the database is down. On Postgres a dead database answers only after the pool's 30 s timeout. The Docker and Caddy checks time out sooner, and a timeout counts as a failure.
- `docker compose ps` shows the app as `unhealthy` after about 30 s of failures. Nothing restarts it automatically.
- Caddy checks `/healthz` every 10 s. While it fails, every request, including the console page, gets a 503 from Caddy. Dispatchers then switch to [runbook-downtime.md](runbook-downtime.md).
- `backup` turns `unhealthy` when its newest dump is more than 26 hours old, so one missed night shows. `offsite` does the same when its last good copy is more than 26 hours old.
- **Alert.** `docker compose ps` only shows these states, so add a dead-man check that pings an external monitor while everything is healthy.
  - Create a check at a healthchecks.io-style service: a 15-minute period, a 1-hour grace time, and notifications to your phone. A missing ping then means a failed backup, an unhealthy app, or a dead host.
  - Add a root cron entry on the host, e.g. `/etc/cron.d/ambulance-alert`. Use the folder that holds `docker-compose.yml`, add `offsite` to the list once it is on, and put your check's URL in place of `PING_URL`:
    `*/15 * * * * root cd /srv/Ambulance-AID-BD && for s in app backup; do [ "$(docker compose ps --format '{{.Health}}' $s)" = healthy ] || exit 1; done && curl -fsS -m 10 --retry 3 -o /dev/null PING_URL`
  - A stopped service has no health, so it stops the pings too.
  - This does not see DNS, the certificate or Caddy from outside. The external uptime check below still matters.

## Backups

- Files: `backups/ambulance-YYYY-MM-DD.dump.gpg` (pg_dump custom format, encrypted with gpg AES-256 from `BACKUP_PASSPHRASE`; the plain dump never touches the disk). A same-day rerun replaces that day's file.
- Retention is 14 days, by file age: after every run, good or failed, `ops/backup.sh` deletes dumps (and any older unencrypted `.dump` files) from 14 nights ago or earlier. After many failed nights in a row, no dump is left. The health check and the alert below are there so that cannot happen unnoticed.
- The same 14 days appear in `ops/offsite.sh`, `docs/pilot-plan.md` section 3, `docs/driver-consent-bn-draft.md` and `docs/pilot-agreement-draft.md`. Change them together.
- `backup` refuses to start when `BACKUP_PASSPHRASE` is a `change-me` placeholder or shorter than 24 characters; compose refuses to start at all when it is unset.
- Decrypt by hand (any machine with gpg): `gpg --decrypt backups/FILE.dump.gpg > FILE.dump`.
- A failure prints `BACKUP FAILED` in `docker compose logs backup`, and `backup` turns `unhealthy` within 26 hours of the last good dump ([Health](#health)).
- Deleted GPS pings (90-day retention) can survive in these dumps for up to 14 more days. `docs/pilot-plan.md` section 3 says so.
- **Offsite copy** (step 6 of the first deploy). Until it runs, the dumps sit on the same disk as the database, so losing the host loses both.
  1. Choose storage with access keys, not a browser login (an S3-compatible bucket, Backblaze B2, or SFTP on another machine). Provider, account and region are the owner's call; whether it may be outside Bangladesh is a question for counsel (`docs/pilot-plan.md` section 3).
     - Preferred: a versioned bucket (object lock optional) and a key with `s3:ListBucket`, `s3:PutObject` and `s3:GetObject` (rclone checks each upload with a HEAD request, which needs read) but no delete rights (no `DeleteObject`, no `DeleteObjectVersion`). A stolen host key then cannot wipe the offsite copies, and re-uploading the same day's dump after a backup rerun only adds a new version. Retention is then the bucket's job, and the 14 days must cover a version's whole life, not each lifecycle step:
       - S3 counts lifecycle days from upload, rounds up to the next midnight UTC and deletes asynchronously. An expired current version becomes a noncurrent version whose own clock starts then, so two 14-day rules would keep a dump about 28 days.
       - So set current-version expiration to 4 days and noncurrent-version expiration to 4 days, remove expired delete markers, and abort incomplete multipart uploads after 1 day (an interrupted upload leaves encrypted parts that the version rules never see). Any object-lock retention must be 4 days or less, or the versions cannot be deleted. Eligible for deletion at most 2 days before upload (below) + 5 + 5 = 12 days after the dump was made. The offsite copy then holds about the last 4 nights; the host still keeps 14.
       - S3 deletes eligible objects asynchronously and does not promise when (usually within a day or two), so this mode aims at 14 days but cannot guarantee it. The mode below is tighter but is not a hard limit either: see there.
       - Set `BACKUP_OFFSITE_PRUNE=0` in `.env`. `ops/offsite.sh` then skips its own delete step, which such a key cannot run, and uploads only dumps under 2 days old, so a dump delayed by an outage stays on the host instead of starting a new lifecycle offsite.
       - Other S3-compatible providers round and delay differently: check theirs keep the total under 14 days.
     - Otherwise: an unversioned bucket (versioning never turned on, so a delete really removes the file; on a versioned bucket `rclone delete` only hides it and the old versions stay) or an SFTP folder, and a key with write and delete rights on that bucket or folder only. `ops/offsite.sh` deletes copies 13 days old or more on every run, so with the nightly run none reaches 14 days. If `offsite` is down (host off, remote unreachable), copies wait until it runs again; the health check and the alert show that.
  2. Write `rclone.conf` next to `docker-compose.yml` (gitignored) with one remote, e.g. from `docker run --rm -it -v "$PWD:/config/rclone" rclone/rclone:1.75.2 config`. Create the file before step 3, or Docker mounts an empty directory in its place. It is mounted read-only, so remotes that refresh OAuth tokens will not work. Make it owned by root and readable only by root: `sudo chown root:root rclone.conf && sudo chmod 600 rclone.conf`. `offsite` runs as root with all capabilities dropped, so it cannot read a 0600 file that belongs to another user, and every run fails with `OFFSITE FAILED`.
  3. In `.env`: `BACKUP_OFFSITE=REMOTE:bucket/ambulance` and `COMPOSE_PROFILES=offsite`. Then `docker compose up -d`.
  4. `docker compose logs offsite` shows `offsite ok: N dumps at ..., newest FILE` or `OFFSITE FAILED` (retried within the hour; on a fresh start the first run fails until `backup` writes its first dump), and `docker compose ps offsite` shows `healthy` while the last successful run (newest local dump confirmed on the remote) is under 26 hours old. It is a last-success check, not a live one: after a failed copy it stays `healthy` until that marker ages out, so watch the logs for `OFFSITE FAILED` too. In the default mode, copies 13 days old or more are deleted there on each run. Add `offsite` to the alert's list of services.
  5. Only `*.dump.gpg` files leave the host. To restore from offsite on a new host: `docker run --rm -v "$PWD:/config/rclone" -v "$PWD/backups:/backups" rclone/rclone:1.75.2 copy REMOTE:bucket/ambulance /backups`, then the restore below.
     - On a versioned bucket, if a day's current dump is bad, an older version of it can still be fetched within its lifecycle: add `--s3-version-at "YYYY-MM-DD HH:MM:SS"` (the moment before the bad upload) to that `copy` command. That needs a key with `s3:ListBucketVersions` and `s3:GetObjectVersion` (an admin key, not the host's).

## Restore drill (monthly, and after any change to `ops/` or `docker-compose.yml`)

Restore only dumps from your own storage (this host's `backups/` or your own offsite copy). A dump is a program for the database, so treat any file from elsewhere as untrusted.

1. `ops/restore.sh backups/ambulance-YYYY-MM-DD.dump.gpg` (the newest file). It decrypts with `BACKUP_PASSPHRASE` from `.env`; a wrong passphrase stops it with "decryption failed".
   - It refuses any file that was not really encrypted with `BACKUP_PASSPHRASE` ("not a dump encrypted with BACKUP_PASSPHRASE"), including a gpg file with no encryption at all. A plain `.dump` is refused unless you add `--unencrypted`; use that only for a dump you made yourself.
   - It loads the dump into a scratch database `restore_drill` as `restore_loader`, a role without superuser rights that the script creates, prints the row count of every table, and drops the scratch database. A dump that tries to run programs or needs superuser rights fails with "permission denied".
   - It does not change the live database.
2. Check the counts are plausible: `missions` and `mission_audit` close to what the console shows, `alembic_version` 1.
3. Write the date and the result in the "Verified" section below.

**Real restore** (data lost or corrupted):
- Run `ops/restore.sh backups/FILE.dump.gpg --live` and type `RESTORE` when asked.
- The script first does the drill steps. It then stops `app` and `backup`, hands every restored object from `restore_loader` to `postgres`, and renames the live database to `ambulance_before_restore`. The restored copy becomes `ambulance`. `docker compose up -d` then upgrades the schema if needed and re-applies the grants.
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

Third run, 2026-10-15: `main` at `eea84a7`, then with the chunked-body cap. The image built, `migrate` exited 0, `app` turned healthy, and `/healthz` through Caddy returned 200 `{"ok":true}`. A 70 KB chunked POST sent straight to the app (no Content-Length, past Caddy) returned 413. `docker compose down -v` cleaned up.

Fourth run, 2026-10-27 (encrypted dumps and offsite copy; throwaway project, `BACKUP_OFFSITE` set to a local folder, `rclone.conf` empty): `backup` wrote `ambulance-DATE.dump.gpg` (gpg symmetric packet, no plain dump on disk). `offsite` logged `offsite ok: 1 dumps` and the folder held the same file. After `bootstrap admin`, `docker compose restart backup` and the drill on the `.gpg` file printed `users 1` and "drill OK". With a wrong passphrase the drill stopped with "decryption failed: Bad session key". A `change-me` passphrase made `backup` refuse to start. Not run: `--live` on an encrypted dump, a real offsite remote, the 20:30 UTC timer, the 15-day offsite delete.

Fifth run, 2026-11-08 (restore checks; throwaway project `amb2t`, Caddy moved to ports 18800/18801, random secrets): after `bootstrap admin`, the nightly `.gpg` dump printed `users 1` and "drill OK". Refused with "not a dump encrypted with BACKUP_PASSPHRASE": a `gpg --store` file (no encryption) and that file glued in front of a real dump. A dump encrypted with the right passphrase whose table or view runs `COPY ... TO PROGRAM` failed with "permission denied" and wrote nothing in the `db` container. A plain `.dump` was refused without `--unencrypted` and restored with it. `--live` on the encrypted dump: `ambulance` and all its tables owned by `postgres`, `restore_loader` owns nothing, `migrate` re-applied the `ambulance_app` grants, `app` healthy. `docker compose down -v` cleaned up.

Sixth run, 2026-11-08 (container hardening, log rotation, time-based retention, backup health checks; throwaway project on `main` with this change, caddy on ports 18860/18861):
- **Startup.** `docker compose up -d --build --wait` came up healthy: `db`, `app`, `backup` healthy, `migrate` exited 0, `caddy` running. `/healthz` and `/console/` through Caddy returned 200, plain HTTP returned 308.
- **Hardening.** In `app` (uid 999) and `offsite`, `CapEff` was 0 and `NoNewPrivs` 1. In `caddy`, `CapEff` was `0x400` (`NET_BIND_SERVICE` only). Writing to `/srv` in `app` failed with "Read-only file system". `docker inspect` showed json-file with `max-size 10m`, `max-file 5`, 512 MB and 200 processes on `app`. With `DOMAIN=localhost`, Caddy logged that it could not install its local root certificate into the read-only system trust store. A real domain gets a public certificate and does not need that.
- **Drill.** After `bootstrap admin` and `docker compose restart backup`, the restore drill printed `users 1` and "drill OK".
- **Failed nights.** 20 seeded dumps, 2 to 21 days old, and a stub `pg_dump` that exits 1: `backup` logged `BACKUP FAILED`, deleted the dumps 14 days old and older (12 left, 2 to 13 days old), and showed `unhealthy`. Back on the real `pg_dump` it showed `healthy` again.
- **Offsite.** With a local folder as the remote and copies 335, 359 and 361 hours old: the 359 h and 361 h copies were deleted, the 335 h copy was kept, today's dump was copied, and `offsite` showed `healthy` with no capabilities. A remote that does not exist gave `OFFSITE FAILED` and `unhealthy`.
- `backend/tests/test_ops_backup.py` checks the retention in `ops/backup.sh` without Docker.

Not checked:
- a real host, DNS, or a Let's Encrypt certificate
- the 20:00 UTC timer firing
- 14-day retention over real days
- the alert cron entry on a real host, UFW and the SSH settings
- a reboot
- a phone, the Leaflet map and the QR library (round B)

## Not done

- **OWNER TODO: hosting account and host.** Choose the provider and region; in-country hosting is an open question for counsel.
- **OWNER TODO: uptime alert to the owner's phone.** Use an external check of `https://DOMAIN/healthz`, next to the dead-man alert in [Health](#health).
- Log shipping, error tracking, a staging copy, rate limiting at the proxy, and tagged images for rollback.
