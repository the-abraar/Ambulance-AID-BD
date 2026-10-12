import hashlib
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config


def migrate(path: str) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(cfg, "head")


def connect(path: str) -> sqlite3.Connection:
    migrate(path)
    db = sqlite3.connect(path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    return db


def hash_token(tok: str) -> str:
    # shortcut: unsalted sha256 is fine only for high-entropy random tokens (never passwords).
    return hashlib.sha256(tok.encode()).hexdigest()
