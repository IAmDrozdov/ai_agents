"""sqlite access for diary.sqlite3: WAL mode, a connection per call."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    day        TEXT NOT NULL,
    text       TEXT NOT NULL CHECK (length(text) BETWEEN 1 AND 120),
    level      TEXT NOT NULL DEFAULT 'day' CHECK (level IN ('day', 'week', 'month', 'year')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS entries_day ON entries(day);

CREATE TABLE IF NOT EXISTS marks (
    day  TEXT PRIMARY KEY,
    mark TEXT NOT NULL CHECK (mark IN ('dead', 'meh', 'fire'))
);
"""


class Database:
    """Path holder; every operation opens its own short-lived connection."""

    def __init__(self, path: str) -> None:
        self.path = path

    @contextmanager
    def session(self, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
        """One transaction on a fresh connection: commit on success, roll back on error, always close."""
        if readonly:
            conn = sqlite3.connect(
                Path(self.path).resolve().as_uri() + "?mode=ro", uri=True, timeout=5
            )
        else:
            conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init(self) -> None:
        """Create the schema; safe to call on every start."""
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.session() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
