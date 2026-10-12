import hashlib
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from psycopg_pool import ConnectionPool

IntegrityError = (sqlite3.IntegrityError, psycopg.IntegrityError)
TOKEN_TTL_DAYS = 90  # keep equal to the constant in migration 0004
_pools: dict[str, ConnectionPool] = {}
_pools_lock = threading.Lock()


def _is_pg(target: str) -> bool:
    return target.startswith(("postgresql://", "postgres://"))


def migrate(target: str) -> None:
    """`target` is a SQLite file path or a postgresql:// URL."""
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "migrations"))
    url = target.replace("postgres://", "postgresql://", 1).replace("postgresql://", "postgresql+psycopg://", 1) \
        if _is_pg(target) else f"sqlite:///{target}"
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    if _is_pg(target):  # several workers start at once: one migrates, the rest wait (lock frees when the connection closes)
        with psycopg.connect(target, autocommit=True) as lock:
            lock.execute("SELECT pg_advisory_lock(727274)")
            command.upgrade(cfg, "head")
        return
    command.upgrade(cfg, "head")
    with sqlite3.connect(target) as c:  # WAL lets per-request connections read while another writes; persists in the file
        c.execute("PRAGMA journal_mode=WAL")


class Row(tuple):
    """Tuple that also reads by column name, like sqlite3.Row, so both backends look alike."""

    def __new__(cls, keys, vals):
        r = super().__new__(cls, vals)
        r._keys = keys
        return r

    def __getitem__(self, k):
        return tuple.__getitem__(self, self._keys.index(k) if isinstance(k, str) else k)

    def keys(self):
        return list(self._keys)


def _row_factory(cur):
    keys = [c.name for c in cur.description or []]
    return lambda vals: Row(keys, vals)


class Conn:
    """One DB-API connection with `?` placeholders on SQLite and Postgres. Not shared between requests."""

    def __init__(self, raw, pg: bool, pool: ConnectionPool | None = None):
        self.raw, self.pg, self.pool = raw, pg, pool

    def execute(self, sql: str, params=()):
        return self.raw.execute(sql.replace("?", "%s") if self.pg else sql, params)

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        if self.pool:
            self.pool.putconn(self.raw)  # the pool rolls back anything uncommitted
        else:
            self.raw.close()


def open_db(target: str, pooled: bool = True) -> Conn:
    """A SQLite connection, or a Postgres one from a per-URL pool (opened lazily, kept for the process)."""
    if _is_pg(target) and pooled:
        with _pools_lock:
            if target not in _pools:
                _pools[target] = ConnectionPool(target, min_size=1, max_size=10, kwargs={"row_factory": _row_factory},
                                                check=ConnectionPool.check_connection, open=True)
            pool = _pools[target]
        return Conn(pool.getconn(), True, pool)
    if _is_pg(target):
        return Conn(psycopg.connect(target, row_factory=_row_factory), True)
    raw = sqlite3.connect(target, check_same_thread=False, timeout=5)
    raw.row_factory = sqlite3.Row
    return Conn(raw, False)


def close_pools() -> None:
    for pool in _pools.values():
        pool.close()
    _pools.clear()


def connect(target: str) -> Conn:
    migrate(target)
    return open_db(target, pooled=False)  # callers own this connection and may keep it open


def token_expiry() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=TOKEN_TTL_DAYS)).isoformat(timespec="microseconds")


def hash_token(tok: str) -> str:
    # shortcut: unsalted sha256 is fine only for high-entropy random tokens (never passwords).
    return hashlib.sha256(tok.encode()).hexdigest()
