"""Application configuration.

Values are read from environment variables at access time so tests can
point the app at a temporary SQLite database by setting ``LUX_DB_PATH``
before startup.
"""

from __future__ import annotations

import os


def db_path() -> str:
    """SQLite database file (overridable via ``LUX_DB_PATH``)."""
    return os.environ.get("LUX_DB_PATH", "/data/museum.db")


def seed_sample() -> bool:
    """Whether to insert a demo showcase/exhibit on first startup."""
    return os.environ.get("LUX_SEED_SAMPLE", "").lower() in {"1", "true", "yes"}
