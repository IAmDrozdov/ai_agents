"""sqlite access: one file, WAL mode, a connection per call so the bot and the web can share it."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from shared.obs import get_logger

log = get_logger(__name__)

ITEMS_DDL = """
CREATE TABLE IF NOT EXISTS {name} (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    kind                TEXT NOT NULL CHECK (kind IN ('link', 'note', 'file')),
    url                 TEXT,
    url_normalized      TEXT,
    text                TEXT NOT NULL DEFAULT '',
    title               TEXT,
    source              TEXT,
    author              TEXT,
    caption             TEXT,
    gist                TEXT,
    image_url           TEXT,
    file_id             TEXT,
    file_name           TEXT,
    file_mime           TEXT,
    file_size           INTEGER,
    status              TEXT NOT NULL DEFAULT 'new'
                        CHECK (status IN ('new', 'started', 'done')),
    placement           TEXT NOT NULL DEFAULT 'active'
                        CHECK (placement IN ('active', 'archived', 'trashed')),
    reviewed            INTEGER NOT NULL DEFAULT 0,
    enrichment_status   TEXT NOT NULL DEFAULT 'pending'
                        CHECK (enrichment_status IN ('pending', 'done', 'failed', 'skipped')),
    enrichment_attempts INTEGER NOT NULL DEFAULT 0,
    enrichment_error    TEXT,
    next_enrich_at      TEXT,
    tg_chat_id          INTEGER,
    tg_ack_message_id   INTEGER,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    trashed_at          TEXT
);
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS sections (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    slug       TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL,
    emoji      TEXT NOT NULL DEFAULT '',
    color      TEXT NOT NULL DEFAULT '#8a8a8a',
    hint       TEXT NOT NULL DEFAULT '',
    is_builtin INTEGER NOT NULL DEFAULT 0,
    position   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS items_url_normalized
    ON items(url_normalized) WHERE url_normalized IS NOT NULL;
CREATE INDEX IF NOT EXISTS items_placement_status ON items(placement, status, created_at DESC);
CREATE INDEX IF NOT EXISTS items_enrich ON items(enrichment_status, next_enrich_at);

CREATE TABLE IF NOT EXISTS item_previews (
    item_id INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
    mime    TEXT NOT NULL,
    data    BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS item_sections (
    item_id    INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    section_id INTEGER NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
    PRIMARY KEY (item_id, section_id)
);
"""


def _items_sql(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT sql FROM sqlite_master WHERE name='items'").fetchone()
    return row["sql"] if row else ""


def _migrate_items_to_files(conn: sqlite3.Connection) -> None:
    """Rebuild `items` so `kind` accepts 'file' (SQLite cannot alter a CHECK); keeps ids and Sections."""
    columns = ", ".join(r["name"] for r in conn.execute("PRAGMA table_info(items)"))
    conn.commit()
    conn.execute("PRAGMA foreign_keys=OFF")  # a no-op inside a transaction; DROP must not cascade
    try:
        conn.execute("BEGIN")
        conn.execute(ITEMS_DDL.format(name="items_new"))
        conn.execute(f"INSERT INTO items_new({columns}) SELECT {columns} FROM items")
        conn.execute("DROP TABLE items")
        conn.execute("ALTER TABLE items_new RENAME TO items")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise sqlite3.IntegrityError("items migration left dangling references")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)  # the rebuild dropped the indexes
    log.info("notes db: rebuilt items to accept kind 'file'")


class Database:
    """Path holder; every operation opens its own short-lived connection."""

    def __init__(self, path: str) -> None:
        self.path = path

    def connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        if readonly:
            uri = Path(self.path).resolve().as_uri() + "?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=5)
        else:
            conn = sqlite3.connect(self.path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def session(self, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
        """One transaction on a fresh connection: commit on success, roll back on error, always close."""
        conn = self.connect(readonly=readonly)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init(self) -> None:
        """Create the schema and seed the starter Sections; safe to call on every start."""
        from notes.domain.sections import seed_sections

        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.session() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(ITEMS_DDL.format(name="items") + SCHEMA)
            if "'file'" not in _items_sql(conn):
                _migrate_items_to_files(conn)
        seed_sections(self)
