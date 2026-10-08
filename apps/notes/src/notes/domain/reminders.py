"""A Reminder is a Due on any Item (ADR-0011): the Overdue rule, the Due decisions and the reminder pass."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from notes.classify.port import Classifier, ClassifierError, DueRequest
from notes.db import Database
from notes.domain import clock, items
from notes.domain.items import Item
from shared.obs import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class Notice:
    """What the interface is told after Enrichment or a Due decision: the Item and its Due when to announce."""

    item: Item
    due: (
        datetime | None
    )  # aware, in the Zone; set only when the Item just became a Reminder, is todo and the Due is ahead


# Called with the Notice once Enrichment or a Due decision lands.
Notify = Callable[[Notice], Awaitable[None]]

# Overdue: todo with a Due that has passed, read off the clock, never stored (ADR-0011).
# One `?`: clock.stamp(now). is_overdue() is the same rule on a loaded Item; change both or neither.
OVERDUE_SQL = "status='todo' AND due_at IS NOT NULL AND due_at <= ?"


def is_overdue(item: Item, now: datetime | None = None) -> bool:
    """Todo with a Due that has passed: read off the clock, never stored (ADR-0011)."""
    return item.status == "todo" and item.due_at is not None and item.due_at <= clock.stamp(now)


def claim_due(db: Database, *, now: datetime | None = None) -> list[Item]:
    """Todo Reminders whose Due has come, marked sent by the same statement so each goes out once; by id."""
    moment = clock.stamp(now)
    with db.session() as conn:
        rows = conn.execute(
            f"UPDATE items SET reminded_at=? WHERE {OVERDUE_SQL} AND reminded_at IS NULL RETURNING id",
            (moment, moment),
        ).fetchall()
        return items.fetch_many(conn, [int(row["id"]) for row in rows])


def release(db: Database, item: Item) -> None:
    """Hand a claimed Reminder back when sending it failed for a reason worth retrying."""
    with db.session() as conn:
        conn.execute(
            "UPDATE items SET reminded_at=NULL WHERE id=? AND reminded_at=?",
            (item.id, item.reminded_at),
        )


def fill_from_filing(
    db: Database, item: Item, local_due: datetime | None, zone: str, *, now: datetime | None = None
) -> Notice:
    """Enrichment's Due (the Classifier's naive moment in `zone`) fills an empty Due and never replaces one (ADR-0011)."""
    if local_due is None:
        return Notice(item, None)
    due = clock.local_to_utc(local_due, zone)
    if clock.stamp(due) <= item.created_at:
        return Notice(item, None)
    with db.session() as conn:
        cur = conn.execute(
            "UPDATE items SET due_at=?, reminded_at=NULL WHERE id=? AND due_at IS NULL",
            (clock.stamp(due), item.id),
        )
        filled = cur.rowcount == 1
        try:
            refreshed = items.fetch(conn, item.id)
        except KeyError:  # deleted meanwhile
            return Notice(item, None)
    announce = (
        filled
        and refreshed.status == "todo"
        and refreshed.due_at is not None
        and refreshed.due_at > clock.stamp(now)
    )
    if not announce or refreshed.due_at is None:
        return Notice(refreshed, None)
    return Notice(refreshed, clock.local(refreshed.due_at, zone))


async def request_due(
    db: Database, classifier: Classifier, item: Item, words: str, *, now: datetime | None = None
) -> Notice:
    """A re-sent Capture's own words may ask for a reminder; the Item then gets that Due and reopens (ADR-0011)."""
    if not words.strip():
        return Notice(item, None)
    now = now or datetime.now(UTC)
    try:  # the Item is already saved: nothing here may fail the Capture
        zone = await asyncio.to_thread(clock.owner_zone, db)
        request = DueRequest(text=words, now_local=clock.local_clock(now, zone), zone=zone)
        try:
            local = await classifier.due(request)
        except ClassifierError as exc:
            log.warning("notes: could not read a Due from a re-sent Capture: %s", exc)
            return Notice(item, None)
        if local is None:
            return Notice(item, None)
        due = clock.local_to_utc(local, zone)
        if due <= now:  # an explicit request is for the future only
            return Notice(item, None)
        try:
            updated = await asyncio.to_thread(_set, db, item.id, due, now)
        except KeyError:  # deleted meanwhile
            return Notice(item, None)
        return Notice(updated, clock.local(updated.due_at, zone) if updated.due_at else None)
    except Exception:
        log.exception("notes: reading a Due from a re-sent Capture failed")
        return Notice(item, None)


def _set(db: Database, item_id: int, due: datetime, now: datetime) -> Item:
    """The Due replaces any old one and the Item goes back to todo (ADR-0011); KeyError if missing."""
    with db.session() as conn:
        cur = conn.execute(
            "UPDATE items SET due_at=?, reminded_at=NULL, status='todo', done_at=NULL, updated_at=? WHERE id=?",
            (clock.stamp(due), clock.stamp(now), item_id),
        )
        if cur.rowcount == 0:
            raise KeyError(item_id)
        return items.fetch(conn, item_id)
