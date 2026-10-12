# Deploy (docker compose, untested)

The files `docker-compose.yml`, `Caddyfile` and `backend/Dockerfile` were written without a running Docker daemon; only `docker compose config` was run. Treat the first deploy as the test and fix what breaks.

1. Point DNS for your domain at the host; open ports 80 and 443. HTTPS is required: phone GPS does not work over plain HTTP.
2. `cp .env.example .env` and set `DOMAIN` and a long random `POSTGRES_PASSWORD`.
3. `docker compose up -d --build`. Migrations run when the app starts.
4. Create the first dispatcher (token is printed once): `docker compose run --rm app python -m app.bootstrap dispatcher NAME`.
5. Open `https://DOMAIN/console/`; drivers use `https://DOMAIN/driver/`.
6. Back up the `pgdata` volume (`pg_dump`) on a schedule you have tested a restore from.

Not done: log shipping, monitoring and alerts, backups, a staging copy, rate limiting at the proxy. Add them before real operations.
