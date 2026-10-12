import os

import pytest


@pytest.fixture
def target(tmp_path):
    """SQLite file by default; with TEST_DATABASE_URL set, a freshly emptied Postgres schema."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        return str(tmp_path / "t.db")
    import psycopg
    from app.db import close_pools
    close_pools()  # pooled connections would otherwise be killed under the pool's feet
    with psycopg.connect(url, autocommit=True) as c:
        # fixtures leave connections open inside a transaction; they would block the DROP
        c.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                  "WHERE datname=current_database() AND pid<>pg_backend_pid()")
        c.execute("DROP SCHEMA public CASCADE")
        c.execute("CREATE SCHEMA public")
    return url
