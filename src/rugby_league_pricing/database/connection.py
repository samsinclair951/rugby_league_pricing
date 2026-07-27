from __future__ import annotations

import sqlite3
from pathlib import Path

PROJECT_ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "pyproject.toml").exists()
)

DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "rugby_league.db"


def get_connection(
    database_path: Path = DEFAULT_DATABASE_PATH,
) -> sqlite3.Connection:
    """Open a SQLite connection with foreign keys enabled."""
    connection = sqlite3.connect(database_path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
