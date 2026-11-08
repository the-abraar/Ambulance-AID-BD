"""One-shot compose `migrate` service: apply migrations as the owner, then give the app's own role least privilege.

The app role (`ambulance_app`, not a superuser) gets only what the app's code uses: SELECT and INSERT on every table,
UPDATE and DELETE only where listed below, and UPDATE on users only for the token columns (never `admin` or `role`).
Every `*_audit` table is therefore append-only, and the role cannot change the schema. Grants are rebuilt from scratch on
every run, so a new table gets SELECT and INSERT only; add it to UPDATE/DELETE below if the app needs more.
`docker compose up` runs this before the app starts, so tables from a new migration get their grants on the next deploy.
"""
import os

import psycopg
from psycopg import sql

from app.db import migrate

AUDIT = r"%\_audit"  # LIKE pattern: a table named *_audit must stay append-only for the app
UPDATE = ["missions", "drivers", "vehicles", "pairing_codes", "ping_limit"]  # fixed names, never user input
DELETE = ["pairing_codes", "ping_limit", "rate_events", "vehicle_pings"]  # what the prune and pairing code delete
url = os.environ["AMBULANCE_DB_PATH"]  # the owner's URL; the app connects with APP_DB_PASSWORD as ambulance_app
migrate(url)
with psycopg.connect(url) as c:  # one transaction: the app never sees a half-applied set of grants
    c.execute("DO $$BEGIN CREATE ROLE ambulance_app; EXCEPTION WHEN duplicate_object THEN NULL; END$$")
    c.execute(sql.SQL("ALTER ROLE ambulance_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}")
              .format(sql.Literal(os.environ["APP_DB_PASSWORD"])))
    c.execute(f"""
        REVOKE ALL ON ALL TABLES IN SCHEMA public FROM ambulance_app;
        GRANT USAGE ON SCHEMA public TO ambulance_app;
        GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA public TO ambulance_app;
        GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO ambulance_app;
        REVOKE INSERT ON alembic_version FROM ambulance_app;
        GRANT UPDATE ON {", ".join(UPDATE)} TO ambulance_app;
        GRANT UPDATE (token_hash, revoked_at, token_expires_at) ON users TO ambulance_app;
        GRANT DELETE ON {", ".join(DELETE)} TO ambulance_app;
    """)
    audit = [r[0] for r in c.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename LIKE %s "
                                     "ORDER BY 1", [AUDIT])]
    assert {"mission_audit", "auth_audit"} <= set(audit), audit
    bad = c.execute("SELECT t, p FROM unnest(%s::text[]) t, unnest(ARRAY['UPDATE','DELETE','TRUNCATE']) p "
                    "WHERE has_table_privilege('ambulance_app', t, p)", [audit]).fetchall()
    assert not bad, f"ambulance_app can still change audit rows: {bad}"
    bad = c.execute("SELECT col FROM unnest(ARRAY['admin','role']) col "
                    "WHERE has_column_privilege('ambulance_app', 'users', col, 'UPDATE')").fetchall()
    assert not bad, f"ambulance_app can change users' privileges: {bad}"
print("migrate: schema at head; ambulance_app has least privilege; INSERT and SELECT only on", ", ".join(audit))
