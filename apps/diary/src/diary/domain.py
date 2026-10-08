"""The diary's rules over its store: Entries, Marks, Levels, Summaries, the Dashboard (CONTEXT.md)."""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal, get_args

from diary.db import Database

Level = Literal["day", "week", "month", "year"]
Mark = Literal["dead", "meh", "fire"]
LEVELS: tuple[Level, ...] = get_args(Level)
MARKS: tuple[Mark, ...] = get_args(Mark)
MAX_TEXT = 120
FIRST_YEAR, LAST_YEAR = 1970, 2100  # a Day outside is refused, so window arithmetic never overflows
TOP_SUGGESTIONS = 5
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


class DiaryError(ValueError):
    """A write the diary refuses; the message is for the Owner."""


@dataclass(frozen=True)
class Entry:
    id: int
    day: date
    text: str
    level: Level


@dataclass(frozen=True)
class Day:
    day: date
    mark: Mark | None
    entries: list[Entry]


@dataclass(frozen=True)
class Week:
    start: date
    days: list[Day]  # Monday to Sunday
    summary: list[Entry]  # week Level or higher


@dataclass(frozen=True)
class Summary:
    summary: list[Entry]
    candidates: list[Entry]  # exactly one Level below, to raise


@dataclass(frozen=True)
class Dashboard:
    year: int
    marks: dict[date, Mark]
    entries: int
    days_with_entry: int
    fire_days: int
    streak: int
    top_entry: tuple[str, int] | None
    best_month: int | None


def parse_day(text: str) -> date:
    """A Day from `YYYY-MM-DD`; DiaryError on anything else."""
    try:
        day = date.fromisoformat(text) if _DAY.fullmatch(text) else None
    except ValueError:
        day = None
    if day is None or not FIRST_YEAR <= day.year <= LAST_YEAR:
        raise DiaryError("Неверная дата")
    return day


def clean_text(text: str) -> str:
    """An Entry's text trimmed; DiaryError when empty or longer than MAX_TEXT."""
    cleaned = text.strip()
    if not cleaned:
        raise DiaryError("Пустая запись")
    if len(cleaned) > MAX_TEXT:
        raise DiaryError(f"Запись длиннее {MAX_TEXT} символов")
    return cleaned


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _entry(row: sqlite3.Row) -> Entry:
    return Entry(
        id=row["id"], day=date.fromisoformat(row["day"]), text=row["text"], level=row["level"]
    )


def _entries(
    conn: sqlite3.Connection, first: date, last: date, levels: tuple[Level, ...]
) -> list[Entry]:
    marks = ",".join("?" * len(levels))
    rows = conn.execute(
        f"SELECT id, day, text, level FROM entries WHERE day BETWEEN ? AND ? AND level IN ({marks}) "
        "ORDER BY day, id",
        (first.isoformat(), last.isoformat(), *levels),
    )
    return [_entry(row) for row in rows]


def _day(conn: sqlite3.Connection, day: date) -> Day:
    row = conn.execute("SELECT mark FROM marks WHERE day=?", (day.isoformat(),)).fetchone()
    return Day(day=day, mark=row["mark"] if row else None, entries=_entries(conn, day, day, LEVELS))


def _get(conn: sqlite3.Connection, entry_id: int) -> Entry | None:
    row = conn.execute(
        "SELECT id, day, text, level FROM entries WHERE id=?", (entry_id,)
    ).fetchone()
    return _entry(row) if row else None


# --- writes ----------------------------------------------------------------------------------


def add_entry(db: Database, day: date, text: str) -> Day:
    """A new day-Level Entry; answers the Day as it now stands."""
    cleaned = clean_text(text)
    with db.session() as conn:
        conn.execute("INSERT INTO entries(day, text) VALUES (?, ?)", (day.isoformat(), cleaned))
        return _day(conn, day)


def edit_entry(db: Database, entry_id: int, text: str) -> Day | None:
    """New text for an Entry, so every Summary it sits in reads it; None when it is gone."""
    cleaned = clean_text(text)
    with db.session() as conn:
        entry = _get(conn, entry_id)
        if entry is None:
            return None
        conn.execute(
            "UPDATE entries SET text=?, updated_at=datetime('now') WHERE id=?", (cleaned, entry_id)
        )
        return _day(conn, entry.day)


def delete_entry(db: Database, entry_id: int) -> Day | None:
    """Removes the Entry from its Day and every Summary; None when it is gone."""
    with db.session() as conn:
        entry = _get(conn, entry_id)
        if entry is None:
            return None
        conn.execute("DELETE FROM entries WHERE id=?", (entry_id,))
        return _day(conn, entry.day)


def set_mark(db: Database, day: date, mark: str | None) -> Day:
    """Sets the Day's Mark, or clears it with None."""
    if mark is not None and mark not in MARKS:
        raise DiaryError("Неизвестная оценка дня")
    with db.session() as conn:
        if mark is None:
            conn.execute("DELETE FROM marks WHERE day=?", (day.isoformat(),))
        else:
            conn.execute(
                "INSERT INTO marks(day, mark) VALUES (?, ?) ON CONFLICT(day) DO UPDATE SET mark=excluded.mark",
                (day.isoformat(), mark),
            )
        return _day(conn, day)


def _step(db: Database, entry_id: int, by: int) -> Entry | None:
    with db.session() as conn:
        entry = _get(conn, entry_id)
        if entry is None:
            return None
        at = LEVELS.index(entry.level) + by
        if not 0 <= at < len(LEVELS):
            raise DiaryError("Выше года не поднять" if by > 0 else "Ниже дня не опустить")
        conn.execute(
            "UPDATE entries SET level=?, updated_at=datetime('now') WHERE id=?",
            (LEVELS[at], entry_id),
        )
        return _get(conn, entry_id)


def raise_entry(db: Database, entry_id: int) -> Entry | None:
    """One Level up (day → week → month → year); DiaryError at year."""
    return _step(db, entry_id, 1)


def lower_entry(db: Database, entry_id: int) -> Entry | None:
    """One Level down; DiaryError at day."""
    return _step(db, entry_id, -1)


# --- reads -----------------------------------------------------------------------------------


def day(db: Database, day: date) -> Day:
    with db.session(readonly=True) as conn:
        return _day(conn, day)


def week(db: Database, any_day: date) -> Week:
    """The Week holding `any_day`: seven Days with Marks and Entries, and its Summary."""
    start = monday(any_day)
    end = start + timedelta(days=6)
    with db.session(readonly=True) as conn:
        entries = _entries(conn, start, end, LEVELS)
        marks = dict(
            conn.execute(
                "SELECT day, mark FROM marks WHERE day BETWEEN ? AND ?",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        )
    days = []
    for offset in range(7):
        current = start + timedelta(days=offset)
        days.append(
            Day(
                day=current,
                mark=marks.get(current.isoformat()),
                entries=[e for e in entries if e.day == current],
            )
        )
    return Week(start=start, days=days, summary=[e for e in entries if e.level != "day"])


def month(db: Database, year: int, month: int) -> Summary:
    """The Month's Summary (month Level or higher) and its week-Level Entries as candidates."""
    first = date(year, month, 1)
    last = (first + timedelta(days=31)).replace(day=1) - timedelta(days=1)
    with db.session(readonly=True) as conn:
        return Summary(
            summary=_entries(conn, first, last, ("month", "year")),
            candidates=_entries(conn, first, last, ("week",)),
        )


def year(db: Database, year: int) -> Summary:
    """The Year's Summary (year Level) and its month-Level Entries as candidates."""
    first, last = date(year, 1, 1), date(year, 12, 31)
    with db.session(readonly=True) as conn:
        return Summary(
            summary=_entries(conn, first, last, ("year",)),
            candidates=_entries(conn, first, last, ("month",)),
        )


def streak(written: set[date], today: date) -> int:
    """Consecutive Days with an Entry ending today, or yesterday while today is still empty."""
    current = today if today in written else today - timedelta(days=1)
    count = 0
    while current in written:
        count += 1
        current -= timedelta(days=1)
    return count


def dashboard(db: Database, year: int, today: date) -> Dashboard:
    """One Year's Day map of Marks, counts, the current Streak, the most repeated Entry, the best Month."""
    first, last = date(year, 1, 1), date(year, 12, 31)
    with db.session(readonly=True) as conn:
        entries = _entries(conn, first, last, LEVELS)
        marks: dict[date, Mark] = {
            date.fromisoformat(row["day"]): row["mark"]
            for row in conn.execute(
                "SELECT day, mark FROM marks WHERE day BETWEEN ? AND ?",
                (first.isoformat(), last.isoformat()),
            )
        }
        written = {
            date.fromisoformat(row["day"])
            for row in conn.execute(
                "SELECT DISTINCT day FROM entries WHERE day <= ?", (today.isoformat(),)
            )
        }

    counts = Counter(e.text for e in entries)
    latest = {e.text: (e.day, e.id) for e in entries}  # ordered by day, id: the last one wins
    top_entry = None
    if counts:
        text = max(counts, key=lambda t: (counts[t], latest[t]))
        if counts[text] >= 2:
            top_entry = (text, counts[text])

    best_month = None
    if entries or marks:
        fire = Counter(d.month for d, m in marks.items() if m == "fire")
        written_by_month = Counter(e.day.month for e in entries)
        best_month = max(range(1, 13), key=lambda m: (fire[m], written_by_month[m], -m))

    return Dashboard(
        year=year,
        marks=marks,
        entries=len(entries),
        days_with_entry=len({e.day for e in entries}),
        fire_days=sum(1 for m in marks.values() if m == "fire"),
        streak=streak(written, today),
        top_entry=top_entry,
        best_month=best_month,
    )


def suggestions(db: Database, prefix: str = "", limit: int = TOP_SUGGESTIONS) -> list[str]:
    """Distinct past Entry texts starting with `prefix` (any case), most frequent first, then most recent."""
    wanted = prefix.strip().casefold()
    with db.session(readonly=True) as conn:
        rows = conn.execute(
            "SELECT text, count(*) AS n, max(day) AS last FROM entries GROUP BY text "
            "ORDER BY n DESC, last DESC, text"
        ).fetchall()
    found = [row["text"] for row in rows if row["text"].casefold().startswith(wanted)]
    return found[:limit]
