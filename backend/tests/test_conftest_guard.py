import pytest

from tests.conftest import ANY_DB_OVERRIDE, APP_ROLE, app_role_url, check_test_db_url


@pytest.mark.parametrize("url", ["postgresql://u:p@h:5432/ambulance_test", "postgresql://h/test", "postgres://h/TestDB"])
def test_test_database_names_pass(url):
    check_test_db_url(url, env={})


@pytest.mark.parametrize("url", ["postgresql://u:p@h:5432/ambulance", "postgresql://h/postgres", "postgresql://h/"])
def test_other_databases_are_refused(url):
    with pytest.raises(pytest.UsageError):
        check_test_db_url(url, env={})
    check_test_db_url(url, env={ANY_DB_OVERRIDE: "1"})  # explicit override


def test_app_role_mode_connects_as_ambulance_app(target):
    import os
    if os.environ.get(APP_ROLE) != "1":
        pytest.skip(f"needs {APP_ROLE}=1")
    import psycopg
    with psycopg.connect(target) as c:
        assert c.execute("SELECT rolname, rolsuper FROM pg_roles WHERE rolname = current_user").fetchone() == (
            "ambulance_app", False)


def test_app_role_mode_refuses_a_shared_cluster(target):
    import os
    if os.environ.get(APP_ROLE) != "1":
        pytest.skip(f"needs {APP_ROLE}=1")
    import psycopg
    owner = os.environ["TEST_DATABASE_URL"]
    with psycopg.connect(owner, autocommit=True) as c:
        c.execute("CREATE DATABASE app_role_guard_probe")
    try:
        with pytest.raises(pytest.UsageError, match="app_role_guard_probe"):
            app_role_url(owner)
    finally:
        with psycopg.connect(owner, autocommit=True) as c:
            c.execute("DROP DATABASE app_role_guard_probe")


@pytest.mark.parametrize("stmt", ["UPDATE users SET admin=true", "UPDATE users SET role='dispatcher'", "DELETE FROM users",
                                  "DELETE FROM missions", "DELETE FROM drivers", "DELETE FROM vehicles",
                                  "UPDATE vehicle_pings SET lat=0", "UPDATE sms_audit SET result='x'"])
def test_app_role_cannot_escalate_or_delete_core_rows(target, stmt):
    import os
    if os.environ.get(APP_ROLE) != "1":
        pytest.skip(f"needs {APP_ROLE}=1")
    import psycopg
    with psycopg.connect(target) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute(stmt)


def test_app_role_keeps_the_writes_the_app_needs(target):
    import os
    if os.environ.get(APP_ROLE) != "1":
        pytest.skip(f"needs {APP_ROLE}=1")
    import psycopg
    with psycopg.connect(target) as c:  # rolled back on exit (no commit)
        c.execute("UPDATE users SET token_hash=token_hash, revoked_at=revoked_at, token_expires_at=token_expires_at")
        for t in ("missions", "drivers", "vehicles", "pairing_codes", "ping_limit"):
            assert c.execute("SELECT has_table_privilege(%s, 'UPDATE')", [t]).fetchone()[0], t
        for t in ("pairing_codes", "ping_limit", "rate_events", "vehicle_pings"):
            c.execute(f"DELETE FROM {t}")
        c.rollback()
