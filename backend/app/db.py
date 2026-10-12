import hashlib
import sqlite3
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config

IntegrityError = (sqlite3.IntegrityError, psycopg.IntegrityError)


def _is_pg(target: str) -> bool:
    return target.startswith(("postgresql://", "postgres://"))


def migrate(target: str) -> None:
    """`target` is a SQLite file path or a postgresql:// URL."""
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "migrations"))
    url = target.replace("postgres://", "postgresql://", 1).replace("postgresql://", "postgresql+psycopg://", 1) \
        if _is_pg(target) else f"sqlite:///{target}"
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(cfg, "head")
    if not _is_pg(target):  # WAL lets per-request connections read while another writes; persists in the file
        with sqlite3.connect(target) as c:
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

    def __init__(self, raw, pg: bool):
        self.raw, self.pg = raw, pg

    def execute(self, sql: str, params=()):
        return self.raw.execute(sql.replace("?", "%s") if self.pg else sql, params)

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()


def open_db(target: str) -> Conn:
    # shortcut: a new connection per request, no pool; add psycopg_pool when Postgres connect latency matters.
    if _is_pg(target):
        return Conn(psycopg.connect(target, row_factory=_row_factory), True)
    raw = sqlite3.connect(target, check_same_thread=False, timeout=5)
    raw.row_factory = sqlite3.Row
    return Conn(raw, False)


def connect(target: str) -> Conn:
    migrate(target)
    return open_db(target)


def hash_token(tok: str) -> str:
    # shortcut: unsalted sha256 is fine only for high-entropy random tokens (never passwords).
    return hashlib.sha256(tok.encode()).hexdigest()
