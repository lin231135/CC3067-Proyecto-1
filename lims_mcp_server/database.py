"""SQLite connection management for the LIMS MCP server.

Uses only the Python standard library (sqlite3), as proposed: no ORM and
no external database driver.
"""
import os
import sqlite3
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent
SCHEMA_PATH = PACKAGE_DIR / "schema.sql"
DEFAULT_DB_PATH = REPO_ROOT / "data" / "lims.db"

_connection = None


def get_db_path():
    """Resolve the database path, overridable via the LIMS_DB_PATH env var."""
    return Path(os.environ.get("LIMS_DB_PATH", str(DEFAULT_DB_PATH)))


def get_connection():
    """Return a lazily-created, process-wide SQLite connection."""
    global _connection
    if _connection is None:
        db_path = get_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _connection = sqlite3.connect(str(db_path), check_same_thread=False)
        _connection.row_factory = sqlite3.Row
        _connection.execute("PRAGMA foreign_keys = ON")
        _init_schema(_connection)
    return _connection


def _init_schema(conn):
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()


def reset_connection():
    """Close and forget the cached connection (used by the seed script)."""
    global _connection
    if _connection is not None:
        _connection.close()
    _connection = None
