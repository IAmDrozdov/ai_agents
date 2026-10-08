"""Lists: the named readings of Items the Mini App shows, each with its rule, order and count (CONTEXT: List)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from notes.db import Database, fold
from notes.domain import clock
from notes.domain.items import ITEM_SELECT, Item, Status, rows_to_items
from notes.domain.reminders import OVERDUE_SQL

# Search reads every text field but the URL ("com" would match every Link).
SEARCH_COLUMNS = (
    "title", "gist", "text", "caption", "transcript", "author", "sender", "source", "file_name",
)  # fmt: skip
NEWEST = "created_at DESC, id DESC"


@dataclass(frozen=True)
class InSection:
    """One Section on one Status, newest first; an Item under several Sections is in each (ADR-0002)."""

    section: str  # slug; an unknown Section is an empty List
    status: Status


@dataclass(frozen=True)
class Overdue:
    """Every Overdue Item, earliest Due first: todo only, every Section (ADR-0011)."""


@dataclass(frozen=True)
class Search:
    """Items whose text fields hold `text` (folded), both Statuses, every Section, newest first."""

    text: str  # no words: an empty List


@dataclass(frozen=True)
class Recheck:
    """The given Items as they are now, in id order, deleted ones left out; never paged."""

    ids: tuple[int, ...]


ItemList = InSection | Overdue | Search | Recheck


@dataclass(frozen=True)
class Page:
    items: list[Item]
    total: int  # the whole List, not only this page


def _plan(lst: ItemList, now: datetime | None) -> tuple[str, list[object], str]:
    """The List's WHERE, its params and its ORDER BY."""
    match lst:
        case Recheck(ids=()):
            return "0", [], "id"
        case Recheck(ids=ids):
            return f"id IN ({','.join('?' * len(ids))})", list(ids), "id"
        case Overdue():
            return OVERDUE_SQL, [clock.stamp(now)], "due_at, id"
        case Search(text=text):
            needle = fold(text.strip())
            if not needle:
                return "0", [], NEWEST
            where = "(" + " OR ".join(f"instr(fold({c}), ?) > 0" for c in SEARCH_COLUMNS) + ")"
            return where, [needle] * len(SEARCH_COLUMNS), NEWEST
        case InSection(section=section, status=status):
            where = (
                "status=? AND id IN (SELECT x.item_id FROM item_sections x "
                "JOIN sections s ON s.id=x.section_id WHERE s.slug=?)"
            )
            return where, [status, section], NEWEST


def read(
    db: Database, lst: ItemList, *, offset: int = 0, limit: int = 50, now: datetime | None = None
) -> Page:
    """One page of the List and its total, from one read transaction; a Recheck ignores offset and limit."""
    where, params, order = _plan(lst, now)
    if isinstance(lst, Recheck):
        offset, limit = 0, -1  # sqlite: no limit
    with db.session(readonly=True) as conn:
        total = int(conn.execute(f"SELECT COUNT(*) FROM items WHERE {where}", params).fetchone()[0])
        rows = conn.execute(
            f"{ITEM_SELECT} WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        return Page(items=rows_to_items(conn, rows), total=total)
