"""The Dashboard read: todo count and Items Captured and done per local day (CONTEXT: Dashboard)."""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from notes.db import Database
from notes.domain import clock
from notes.domain.reminders import OVERDUE_SQL

DayField = Literal["captured", "done"]
DAY_COLUMNS: dict[DayField, str] = {"captured": "created_at", "done": "done_at"}
WEEKS = 26


@dataclass(frozen=True)
class Dashboard:
    todo: int
    overdue: int
    captured: dict[str, int]
    done: dict[str, int]
    first: date
    last: date


def window(today: date, weeks: int = WEEKS) -> tuple[date, date]:
    """Monday `weeks - 1` weeks before this week's Monday, through `today`."""
    return today - timedelta(days=today.weekday() + 7 * (weeks - 1)), today


def _by_day(
    conn: sqlite3.Connection, field: DayField, tz: str, first: date, last: date
) -> dict[str, int]:
    column = DAY_COLUMNS[field]
    rows = conn.execute(
        f"SELECT {column} AS ts FROM items WHERE {column} >= ? AND {column} < ?",
        (clock.local_midnight_utc(first, tz), clock.local_midnight_utc(last + timedelta(1), tz)),
    ).fetchall()
    days = Counter(clock.local_day(row["ts"], tz).isoformat() for row in rows)
    return dict(days)


def dashboard(
    db: Database, tz: str = "UTC", *, now: datetime | None = None, weeks: int = WEEKS
) -> Dashboard:
    """One read transaction; days are the Owner's (`tz`), an unknown zone counts as UTC."""
    today = (now or datetime.now(UTC)).astimezone(clock.zone(tz)).date()
    first, last = window(today, weeks)
    with db.session(readonly=True) as conn:
        todo = int(conn.execute("SELECT COUNT(*) FROM items WHERE status='todo'").fetchone()[0])
        overdue = int(
            conn.execute(
                f"SELECT COUNT(*) FROM items WHERE {OVERDUE_SQL}", (clock.stamp(now),)
            ).fetchone()[0]
        )
        return Dashboard(
            todo=todo,
            overdue=overdue,
            captured=_by_day(conn, "captured", tz, first, last),
            done=_by_day(conn, "done", tz, first, last),
            first=first,
            last=last,
        )
