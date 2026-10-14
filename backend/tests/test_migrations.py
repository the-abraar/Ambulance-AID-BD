from pathlib import Path
import sqlite3

from app.db import migrate


def test_upgrade_from_empty(tmp_path):
    p = str(tmp_path / "m.db")
    migrate(p)
    migrate(p)  # idempotent
    names = {r[0] for r in sqlite3.connect(p).execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"users", "vehicles", "drivers", "missions", "vehicle_pings", "mission_audit", "alembic_version"} <= names


def test_upgrade_0001_to_0002_keeps_data(tmp_path):
    from alembic import command
    from alembic.config import Config
    p = str(tmp_path / "o.db")
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{p}")
    command.upgrade(cfg, "0001")
    db = sqlite3.connect(p)
    db.execute("INSERT INTO missions VALUES ('m1','DISPATCHED','old addr',NULL,NULL,'t','t')")
    db.commit(); db.close()
    migrate(p)
    row = sqlite3.connect(p).execute("SELECT pickup_address,pickup_lat,pickup_lng FROM missions WHERE id='m1'").fetchone()
    assert row == ("old addr", None, None)


def test_upgrade_0002_to_0003_keeps_users(tmp_path):
    from alembic import command
    from alembic.config import Config
    p = str(tmp_path / "u.db")
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{p}")
    command.upgrade(cfg, "0002")
    db = sqlite3.connect(p)
    db.execute("INSERT INTO users VALUES ('u1','n','driver','h')")
    db.commit(); db.close()
    migrate(p)
    assert sqlite3.connect(p).execute("SELECT name,revoked_at FROM users").fetchone() == ("n", None)


def test_upgrade_0003_to_0004_backfills_expiry(tmp_path):
    from alembic import command
    from alembic.config import Config
    p = str(tmp_path / "x.db")
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{p}")
    command.upgrade(cfg, "0003")
    db = sqlite3.connect(p)
    db.execute("INSERT INTO users (id,name,role,token_hash) VALUES ('u1','n','driver','h')")
    db.commit(); db.close()
    migrate(p)
    assert sqlite3.connect(p).execute("SELECT token_expires_at FROM users").fetchone()[0] > "2026"


def test_upgrade_0005_to_0006_promotes_dispatchers_and_repairs_double_dispatch(tmp_path):
    from alembic import command
    from alembic.config import Config
    p = str(tmp_path / "y.db")
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{p}")
    command.upgrade(cfg, "0005")
    db = sqlite3.connect(p)
    db.execute("INSERT INTO users (id,name,role,token_hash,token_expires_at) VALUES ('u1','d','dispatcher','h1','x')")
    db.execute("INSERT INTO users (id,name,role,token_hash,token_expires_at) VALUES ('u2','r','driver','h2','x')")
    db.execute("INSERT INTO vehicles (id,operator,registration,active) VALUES ('v1','o','R',1)")
    db.execute("INSERT INTO drivers (id,name,user_id) VALUES ('d1','r','u2')")
    for mid, t in (("old", "2026-01-01T00:00:00+00:00"), ("new", "2026-01-02T00:00:00+00:00")):  # double dispatch
        db.execute("INSERT INTO missions (id,status,pickup_address,assigned_vehicle_id,assigned_driver_id,created_at,"
                   "updated_at) VALUES (?,'EN_ROUTE_PICKUP','a','v1','d1',?,?)", (mid, t, t))
        db.execute("INSERT INTO mission_audit (mission_id,user_id,from_status,to_status,ts) "
                   "VALUES (?,'u2','DISPATCHED','EN_ROUTE_PICKUP',?)", (mid, t))
    db.commit(); db.close()
    migrate(p)
    db = sqlite3.connect(p)
    assert db.execute("SELECT id, admin FROM users ORDER BY id").fetchall() == [("u1", 1), ("u2", 0)]
    assert db.execute("SELECT id, status, en_route_pickup_at FROM missions ORDER BY id").fetchall() == [
        ("new", "EN_ROUTE_PICKUP", "2026-01-02T00:00:00+00:00"), ("old", "CANCELLED", "2026-01-01T00:00:00+00:00")]
    assert db.execute("SELECT user_id, to_status FROM mission_audit WHERE mission_id='old' ORDER BY id DESC").fetchone() == (
        "migration-0006", "CANCELLED")


def test_concurrent_migrate_on_postgres():
    import os
    from concurrent.futures import ThreadPoolExecutor
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        import pytest
        pytest.skip("needs TEST_DATABASE_URL")
    import psycopg
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE"); c.execute("CREATE SCHEMA public")
    with ThreadPoolExecutor(4) as ex:  # four workers booting at once
        list(ex.map(lambda _: migrate(url), range(4)))
    with psycopg.connect(url) as c:
        assert c.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0006"


def test_0006_states_match_state_machine():
    import importlib.util
    from app.main import TERMINAL
    from app.state_machine import INITIAL, State
    sp = importlib.util.spec_from_file_location("m0006", Path(__file__).resolve().parent.parent / "migrations/versions/0006_dispatch_loop.py")
    m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m)
    assert m.ACTIVE.format(t="") == f"status NOT IN ({','.join(repr(s) for s in TERMINAL)})"  # partial index predicate
    assert m.STEPS == [s.value for s in State if s is not INITIAL]  # one <status>_at column per reachable status
