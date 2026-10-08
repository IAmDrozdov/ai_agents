"""Diary endpoints for the Mini App: a thin adapter over apps/diary (ADR-020)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from diary import domain
from diary.db import Database
from diary.domain import Day, Entry, Summary

from .auth import require_admin

# A DiaryError (bad text, Day, Mark or Level step) is a 422, mapped in app.py.
router = APIRouter(prefix="/api/diary", dependencies=[Depends(require_admin)])

EntryId = Annotated[int, Field(ge=1, le=2**63 - 1)]
Zone = Annotated[str | None, Query(max_length=64)]
DayText = Annotated[str | None, Query(max_length=10)]
YearNumber = Annotated[int, Query(ge=domain.FIRST_YEAR, le=domain.LAST_YEAR)]


class EntryIn(BaseModel):
    """A new Entry; `day` defaults to today in `tz`. The domain trims and bounds the text."""

    model_config = ConfigDict(extra="forbid")
    day: str | None = Field(default=None, max_length=10)
    text: str = Field(max_length=1000)


class EntryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=1000)


class MarkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    day: str = Field(max_length=10)
    mark: str | None = Field(max_length=10)


def get_db(request: Request) -> Database:
    return request.app.state.diary_db


def today(tz: str | None) -> date:
    """The Owner's local date in IANA zone `tz` (UTC when missing or unknown)."""
    try:
        zone = ZoneInfo(tz) if tz else UTC
    except (ZoneInfoNotFoundError, ValueError, OSError):
        zone = UTC
    return datetime.now(zone).date()


def _day_of(text: str | None, tz: str | None) -> date:
    return today(tz) if text is None else domain.parse_day(text)


def _entry_json(entry: Entry) -> dict[str, Any]:
    return {"id": entry.id, "day": entry.day.isoformat(), "text": entry.text, "level": entry.level}


def _day_json(day: Day) -> dict[str, Any]:
    return {
        "day": day.day.isoformat(),
        "mark": day.mark,
        "entries": [{"id": e.id, "text": e.text, "level": e.level} for e in day.entries],
    }


def _summary_json(summary: Summary) -> dict[str, Any]:
    return {
        "summary": [_entry_json(e) for e in summary.summary],
        "candidates": [_entry_json(e) for e in summary.candidates],
    }


def _found[T](value: T | None) -> T:
    if value is None:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    return value


DbDep = Annotated[Database, Depends(get_db)]


@router.get("/week")
def get_week(db: DbDep, day: DayText = None, tz: Zone = None) -> dict[str, Any]:
    """The Week holding `day` (default: today in `tz`)."""
    week = domain.week(db, _day_of(day, tz))
    return {
        "start": week.start.isoformat(),
        "days": [_day_json(d) for d in week.days],
        "summary": [_entry_json(e) for e in week.summary],
    }


@router.get("/month")
def get_month(
    db: DbDep, year: YearNumber, month: Annotated[int, Query(ge=1, le=12)]
) -> dict[str, Any]:
    return _summary_json(domain.month(db, year, month))


@router.get("/year")
def get_year(db: DbDep, year: YearNumber) -> dict[str, Any]:
    return _summary_json(domain.year(db, year))


@router.get("/dashboard")
def get_dashboard(db: DbDep, year: YearNumber | None = None, tz: Zone = None) -> dict[str, Any]:
    """One Year (default: the current one in `tz`); the Streak counts back from today in `tz`."""
    now = today(tz)
    board = domain.dashboard(db, year or now.year, now)
    return {
        "year": board.year,
        "marks": {d.isoformat(): m for d, m in board.marks.items()},
        "entries": board.entries,
        "days_with_entry": board.days_with_entry,
        "fire_days": board.fire_days,
        "streak": board.streak,
        "top_entry": (
            {"text": board.top_entry[0], "count": board.top_entry[1]} if board.top_entry else None
        ),
        "best_month": board.best_month,
    }


@router.get("/suggestions")
def get_suggestions(
    db: DbDep,
    prefix: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=20)] = domain.TOP_SUGGESTIONS,
) -> list[str]:
    return domain.suggestions(db, prefix, limit)


@router.post("/entries", status_code=201)
def create_entry(db: DbDep, body: EntryIn, tz: Zone = None) -> dict[str, Any]:
    """Answers the Day as it now stands."""
    return _day_json(domain.add_entry(db, _day_of(body.day, tz), body.text))


@router.patch("/entries/{entry_id}")
def patch_entry(db: DbDep, entry_id: EntryId, body: EntryPatch) -> dict[str, Any]:
    return _day_json(_found(domain.edit_entry(db, entry_id, body.text)))


@router.delete("/entries/{entry_id}")
def remove_entry(db: DbDep, entry_id: EntryId) -> dict[str, Any]:
    return _day_json(_found(domain.delete_entry(db, entry_id)))


@router.post("/entries/{entry_id}/raise")
def raise_entry(db: DbDep, entry_id: EntryId) -> dict[str, Any]:
    """Answers the Entry with its new Level."""
    return _entry_json(_found(domain.raise_entry(db, entry_id)))


@router.post("/entries/{entry_id}/lower")
def lower_entry(db: DbDep, entry_id: EntryId) -> dict[str, Any]:
    return _entry_json(_found(domain.lower_entry(db, entry_id)))


@router.put("/marks")
def put_mark(db: DbDep, body: MarkIn) -> dict[str, Any]:
    """Sets the Day's Mark (`dead`, `meh`, `fire`), or clears it with null; answers the Day."""
    return _day_json(domain.set_mark(db, domain.parse_day(body.day), body.mark))
