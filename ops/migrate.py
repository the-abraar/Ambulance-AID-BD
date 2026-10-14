"""One-shot compose `migrate` service: apply migrations as the owner, then give the app's own role least privilege.

The app role (`ambulance_app`, not a superuser) may read and write the working tables, but on the audit tables it may
only INSERT and SELECT, and it cannot change the schema. `docker compose up` runs this before the app starts, so new
tables from a new migration get their grants on the next deploy.
"""
import os

import psycopg
from psycopg import sql

from app.db import migrate

AUDIT = ("mission_audit", "auth_audit")
url = os.environ["AMBULANCE_DB_PATH"]  # the owner's URL; the app connects with APP_DB_PASSWORD as ambulance_app
migrate(url)
with psycopg.connect(url) as c:  # one transaction: the app never sees a half-applied set of grants
    c.execute("DO $$BEGIN CREATE ROLE ambulance_app; EXCEPTION WHEN duplicate_object THEN NULL; END$$")
    c.execute(sql.SQL("ALTER ROLE ambulance_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}")
              .format(sql.Literal(os.environ["APP_DB_PASSWORD"])))
    c.execute("""
        GRANT USAGE ON SCHEMA public TO ambulance_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO ambulance_app;
        GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO ambulance_app;
        REVOKE UPDATE, DELETE, TRUNCATE ON mission_audit, auth_audit FROM ambulance_app;
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON alembic_version FROM ambulance_app;
    """)
    bad = c.execute("SELECT t, p FROM unnest(%s::text[]) t, unnest(ARRAY['UPDATE','DELETE','TRUNCATE']) p "
                    "WHERE has_table_privilege('ambulance_app', t, p)", [list(AUDIT)]).fetchall()
    assert not bad, f"ambulance_app can still change audit rows: {bad}"
print("migrate: schema at head; ambulance_app has INSERT and SELECT only on", ", ".join(AUDIT))
