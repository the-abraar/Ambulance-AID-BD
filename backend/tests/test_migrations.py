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
