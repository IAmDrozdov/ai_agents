"""The Dashboard read: todo count and Items Captured and done per local day (CONTEXT: Dashboard)."""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from notes.db import Database
from notes.domain.items import DAY_COLUMNS, DayField, local_midnight_utc, stamp, zone

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
        (local_midnight_utc(first, tz), local_midnight_utc(last + timedelta(1), tz)),
    ).fetchall()
    local = zone(tz)
    days = Counter(
        datetime.strptime(row["ts"], "%Y-%m-%d %H:%M:%S")
        .replace(tzinfo=UTC)
        .astimezone(local)
        .date()
        .isoformat()
        for row in rows
    )
    return dict(days)


def dashboard(
    db: Database, tz: str = "UTC", *, now: datetime | None = None, weeks: int = WEEKS
) -> Dashboard:
    """One read transaction; days are the Owner's (`tz`), an unknown zone counts as UTC."""
    today = (now or datetime.now(UTC)).astimezone(zone(tz)).date()
    first, last = window(today, weeks)
    with db.session(readonly=True) as conn:
        todo = int(conn.execute("SELECT COUNT(*) FROM items WHERE status='todo'").fetchone()[0])
        overdue = int(
            conn.execute(
                "SELECT COUNT(*) FROM items WHERE status='todo' AND due_at IS NOT NULL "
                "AND due_at <= ?",
                (stamp(now),),
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
