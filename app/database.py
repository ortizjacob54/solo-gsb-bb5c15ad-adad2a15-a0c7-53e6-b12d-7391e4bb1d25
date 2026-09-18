"""SQLite persistence layer: connection handling, schema and initial data."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS showcases (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exhibits (
    id                    TEXT PRIMARY KEY,
    showcase_id           TEXT NOT NULL REFERENCES showcases(id),
    name                  TEXT NOT NULL,
    sensitivity           TEXT NOT NULL,
    annual_limit_lux_hour REAL,
    created_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lighting_intervals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    showcase_id TEXT NOT NULL REFERENCES showcases(id),
    exhibit_id  TEXT NOT NULL REFERENCES exhibits(id),
    start_at    TEXT NOT NULL,
    end_at      TEXT NOT NULL,
    lux         REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_intervals_showcase_start
    ON lighting_intervals (showcase_id, start_at);
CREATE INDEX IF NOT EXISTS idx_intervals_exhibit
    ON lighting_intervals (exhibit_id);
"""

# Default annual exposure budget per sensitivity category (CIE 157 /
# conservation practice), in lux·hour per year.
DEFAULT_ANNUAL_LIMIT = {
    "high_sensitivity": 15000.0,      # textiles, watercolours, photographs
    "medium_sensitivity": 150000.0,   # oil/tempera paintings, wood, bone
    "stable": None,                   # metal, stone, glass — no budget cap
}


def connect() -> sqlite3.Connection:
    path = config.db_path()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    """Context manager for non-request code (startup, health checks)."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_conn() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: one connection per request, committed on success."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create the schema on startup (idempotent)."""
    with connection() as conn:
        conn.executescript(SCHEMA)
        if config.seed_sample() and _is_empty(conn):
            _seed(conn)


def _is_empty(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT COUNT(*) FROM showcases").fetchone()[0] == 0


def _seed(conn: sqlite3.Connection) -> None:
    """Insert a small demo dataset used by the README walkthrough."""
    now = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO showcases (id, name, created_at) VALUES (?, ?, ?)",
        ("case-a", "书画厅 A 号展柜", now.isoformat()),
    )
    conn.execute(
        """INSERT INTO exhibits
               (id, showcase_id, name, sensitivity, annual_limit_lux_hour, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ("ex-1", "case-a", "清代绢本设色扇面", "high_sensitivity",
         DEFAULT_ANNUAL_LIMIT["high_sensitivity"], now.isoformat()),
    )
