"""The Owner's zone, remembered from the Mini App (ADR-0011): UTC until it first opens."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from notes.db import Database

ZONE_KEY = "zone"
DEFAULT_ZONE = "UTC"


def get_zone(db: Database) -> str:
    with db.session(readonly=True) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (ZONE_KEY,)).fetchone()
    return row["value"] if row else DEFAULT_ZONE


def remember_zone(db: Database, name: str) -> None:
    """Store `name` when it is a real IANA zone and differs from the stored one."""
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return
    if name == get_zone(db):
        return
    with db.session() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (ZONE_KEY, name),
        )
