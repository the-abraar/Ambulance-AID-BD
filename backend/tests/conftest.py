import os
from urllib.parse import urlparse

import pytest

ANY_DB_OVERRIDE = "TEST_DATABASE_ANY_NAME"


def check_test_db_url(url: str, env=os.environ) -> None:
    """Tests empty the `public` schema and kill other sessions: refuse a database whose name lacks "test"."""
    name = urlparse(url).path.lstrip("/")
    if "test" not in name.lower() and env.get(ANY_DB_OVERRIDE) != "1":
        raise pytest.UsageError(f"TEST_DATABASE_URL names database {name!r}, which lacks 'test'; tests would wipe it. "
                                f"Point it at a test database, or set {ANY_DB_OVERRIDE}=1 if you are sure.")


def pytest_configure(config):
    if os.environ.get("TEST_DATABASE_URL"):  # checked once, before any test (fixture or not) touches the database
        check_test_db_url(os.environ["TEST_DATABASE_URL"])


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
