"""Items: Links and Notes, their Filing, Status and Placement (ADR-0001..0003)."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from notes.db import Database
from notes.domain.sections import OTHER_SLUG, Section, _row_to_section, other_id
from notes.domain.urls import normalize_url

Kind = Literal["link", "note"]
Status = Literal["new", "started", "done"]
Placement = Literal["active", "archived", "trashed"]
EnrichmentStatus = Literal["pending", "done", "failed", "skipped"]
CaptureOutcome = Literal["new", "existing", "restored", "archived"]

TIMESTAMP = "%Y-%m-%d %H:%M:%S"
BACKOFF = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=12),
)
STALE_PENDING = timedelta(minutes=2)


@dataclass(frozen=True)
class Item:
    id: int
    kind: Kind
    url: str | None
    url_normalized: str | None
    text: str
    title: str | None
    source: str | None
    author: str | None
    caption: str | None
    gist: str | None
    image_url: str | None
    status: Status
    placement: Placement
    reviewed: bool
    enrichment_status: EnrichmentStatus
    enrichment_attempts: int
    enrichment_error: str | None
    next_enrich_at: str | None
    tg_chat_id: int | None
    tg_ack_message_id: int | None
    created_at: str
    updated_at: str
    trashed_at: str | None
    sections: tuple[Section, ...]


@dataclass(frozen=True)
class Capture:
    """What a Capture produced: a fresh Item, or the one this link already had."""

    item: Item
    outcome: CaptureOutcome


@dataclass(frozen=True)
class ItemFilter:
    """Which Items a list or bulk action covers; an Item matches if it is in any listed Section."""

    sections: tuple[str, ...] = ()
    status: Status | None = None
    placement: Placement = "active"
    unreviewed: bool = False


@dataclass(frozen=True)
class Page:
    items: list[Item]
    total: int


def stamp(now: datetime | None = None) -> str:
    """UTC timestamp in sqlite's own `datetime('now')` format so comparisons stay textual."""
    return (now or datetime.now(UTC)).astimezone(UTC).strftime(TIMESTAMP)


def _sections_of(conn: sqlite3.Connection, item_id: int) -> tuple[Section, ...]:
    rows = conn.execute(
        "SELECT s.* FROM sections s JOIN item_sections i ON i.section_id = s.id "
        "WHERE i.item_id=? ORDER BY s.position, s.id",
        (item_id,),
    ).fetchall()
    return tuple(_row_to_section(row) for row in rows)


def _row_to_item(conn: sqlite3.Connection, row: sqlite3.Row) -> Item:
    return Item(
        id=int(row["id"]),
        kind=row["kind"],
        url=row["url"],
        url_normalized=row["url_normalized"],
        text=row["text"],
        title=row["title"],
        source=row["source"],
        author=row["author"],
        caption=row["caption"],
        gist=row["gist"],
        image_url=row["image_url"],
        status=row["status"],
        placement=row["placement"],
        reviewed=bool(row["reviewed"]),
        enrichment_status=row["enrichment_status"],
        enrichment_attempts=int(row["enrichment_attempts"]),
        enrichment_error=row["enrichment_error"],
        next_enrich_at=row["next_enrich_at"],
        tg_chat_id=row["tg_chat_id"],
        tg_ack_message_id=row["tg_ack_message_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        trashed_at=row["trashed_at"],
        sections=_sections_of(conn, int(row["id"])),
    )


def _fetch(conn: sqlite3.Connection, item_id: int) -> Item:
    row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if row is None:
        raise KeyError(item_id)
    return _row_to_item(conn, row)


def capture_note(
    db: Database, text: str, *, chat_id: int | None = None, now: datetime | None = None
) -> Item:
    """Save a Note; it lands in Other until the Classifier files it (ADR-0006)."""
    with db.session() as conn:
        cur = conn.execute(
            "INSERT INTO items(kind, text, tg_chat_id, created_at, updated_at) "
            "VALUES ('note', ?, ?, ?, ?)",
            (text, chat_id, stamp(now), stamp(now)),
        )
        item_id = int(cur.lastrowid or 0)
        conn.execute(
            "INSERT INTO item_sections(item_id, section_id) VALUES (?, ?)",
            (item_id, other_id(db)),
        )
        return _fetch(conn, item_id)


def capture_link(
    db: Database,
    url: str,
    annotation: str,
    *,
    chat_id: int | None = None,
    now: datetime | None = None,
) -> Capture:
    """Save a Link once: a repeat returns the existing Item, restoring it if it was trashed."""
    key = normalize_url(url)
    with db.session() as conn:
        # OR IGNORE against the unique key makes a double-send race-free: the loser sees the row.
        cur = conn.execute(
            "INSERT OR IGNORE INTO items"
            "(kind, url, url_normalized, text, tg_chat_id, created_at, updated_at) "
            "VALUES ('link', ?, ?, ?, ?, ?, ?)",
            (url, key, annotation, chat_id, stamp(now), stamp(now)),
        )
        if cur.rowcount == 1:
            item_id = int(cur.lastrowid or 0)
            conn.execute(
                "INSERT INTO item_sections(item_id, section_id) VALUES (?, ?)",
                (item_id, other_id(db)),
            )
            return Capture(_fetch(conn, item_id), "new")
        row = conn.execute("SELECT * FROM items WHERE url_normalized=?", (key,)).fetchone()
        existing = _row_to_item(conn, row)
        if existing.placement == "trashed":
            return Capture(_set_placement(conn, existing.id, "active", now), "restored")
        return Capture(existing, "archived" if existing.placement == "archived" else "existing")


def _set_placement(
    conn: sqlite3.Connection, item_id: int, placement: Placement, now: datetime | None
) -> Item:
    trashed_at = stamp(now) if placement == "trashed" else None
    conn.execute(
        "UPDATE items SET placement=?, trashed_at=?, updated_at=? WHERE id=?",
        (placement, trashed_at, stamp(now), item_id),
    )
    return _fetch(conn, item_id)


def set_placement(
    db: Database, item_id: int, placement: Placement, *, now: datetime | None = None
) -> Item:
    with db.session() as conn:
        return _set_placement(conn, item_id, placement, now)


def _replace_sections(conn: sqlite3.Connection, item_id: int, slugs: Sequence[str]) -> None:
    """Unknown slugs are dropped; an empty Filing falls back to Other (ADR-0002)."""
    rows = (
        conn.execute(
            f"SELECT id FROM sections WHERE slug IN ({','.join('?' * len(slugs))})", tuple(slugs)
        ).fetchall()
        if slugs
        else []
    )
    section_ids = [int(row["id"]) for row in rows]
    if not section_ids:
        section_ids = [
            int(
                conn.execute("SELECT id FROM sections WHERE slug=?", (OTHER_SLUG,)).fetchone()["id"]
            )
        ]
    conn.execute("DELETE FROM item_sections WHERE item_id=?", (item_id,))
    conn.executemany(
        "INSERT INTO item_sections(item_id, section_id) VALUES (?, ?)",
        [(item_id, section_id) for section_id in section_ids],
    )


def set_ack_message(db: Database, item_id: int, *, chat_id: int, message_id: int) -> Item:
    with db.session() as conn:
        conn.execute(
            "UPDATE items SET tg_chat_id=?, tg_ack_message_id=? WHERE id=?",
            (chat_id, message_id, item_id),
        )
        return _fetch(conn, item_id)


def store_enrichment(
    db: Database,
    item_id: int,
    *,
    sections: Sequence[str],
    gist: str | None = None,
    title: str | None = None,
    source: str | None = None,
    author: str | None = None,
    caption: str | None = None,
    image_url: str | None = None,
    error: str | None = None,
    now: datetime | None = None,
) -> Item:
    """Record what Enrichment found and file the Item; the Owner's own Filing is kept once Reviewed.

    Raises KeyError if the Item was deleted while it was being enriched.
    """
    with db.session() as conn:
        cur = conn.execute(
            "UPDATE items SET title=?, source=?, author=?, caption=?, image_url=?, gist=?, "
            "enrichment_status='done', enrichment_error=?, next_enrich_at=NULL, updated_at=? "
            "WHERE id=?",
            (title, source, author, caption, image_url, gist, error, stamp(now), item_id),
        )
        if cur.rowcount == 0:
            raise KeyError(item_id)
        reviewed = conn.execute("SELECT reviewed FROM items WHERE id=?", (item_id,)).fetchone()
        if not reviewed["reviewed"]:
            _replace_sections(conn, item_id, sections)
        return _fetch(conn, item_id)


def schedule_retry(db: Database, item_id: int, error: str, *, now: datetime | None = None) -> Item:
    """Count a transient failure; back off, or give up after the last step of BACKOFF."""
    with db.session() as conn:
        row = conn.execute(
            "SELECT enrichment_attempts FROM items WHERE id=?", (item_id,)
        ).fetchone()
        if row is None:
            raise KeyError(item_id)
        attempts = int(row["enrichment_attempts"]) + 1
        if attempts > len(BACKOFF):
            conn.execute(
                "UPDATE items SET enrichment_status='failed', enrichment_attempts=?, "
                "enrichment_error=?, next_enrich_at=NULL, updated_at=? WHERE id=?",
                (attempts, error, stamp(now), item_id),
            )
        else:
            moment = (now or datetime.now(UTC)).astimezone(UTC)
            conn.execute(
                "UPDATE items SET enrichment_status='pending', enrichment_attempts=?, "
                "enrichment_error=?, next_enrich_at=?, updated_at=? WHERE id=?",
                (attempts, error, stamp(moment + BACKOFF[attempts - 1]), stamp(now), item_id),
            )
        return _fetch(conn, item_id)


def mark_failed(db: Database, item_id: int, error: str, *, now: datetime | None = None) -> Item:
    """Give up on Enrichment now; only a manual re-enrich brings the Item back."""
    with db.session() as conn:
        conn.execute(
            "UPDATE items SET enrichment_status='failed', enrichment_error=?, "
            "next_enrich_at=NULL, updated_at=? WHERE id=?",
            (error, stamp(now), item_id),
        )
        return _fetch(conn, item_id)


def request_reenrich(db: Database, item_id: int, *, now: datetime | None = None) -> Item:
    """Start Enrichment over, immediately due for the sweeper."""
    with db.session() as conn:
        conn.execute(
            "UPDATE items SET enrichment_status='pending', enrichment_attempts=0, "
            "enrichment_error=NULL, next_enrich_at=?, updated_at=? WHERE id=?",
            (stamp(now), stamp(now), item_id),
        )
        return _fetch(conn, item_id)


def claim_due_enrichments(db: Database, *, now: datetime | None = None) -> list[int]:
    """Scheduled retries whose time has come, plus pending Items nothing has touched lately."""
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    with db.session(readonly=True) as conn:
        rows = conn.execute(
            "SELECT id FROM items WHERE enrichment_status='pending' AND ("
            "(next_enrich_at IS NOT NULL AND next_enrich_at <= ?) OR "
            "(next_enrich_at IS NULL AND updated_at <= ?)) ORDER BY id",
            (stamp(moment), stamp(moment - STALE_PENDING)),
        ).fetchall()
    return [int(row["id"]) for row in rows]


def get_item(db: Database, item_id: int) -> Item | None:
    with db.session(readonly=True) as conn:
        try:
            return _fetch(conn, item_id)
        except KeyError:
            return None


def _where(flt: ItemFilter) -> tuple[str, list[object]]:
    clauses = ["placement=?"]
    params: list[object] = [flt.placement]
    if flt.status is not None:
        clauses.append("status=?")
        params.append(flt.status)
    if flt.unreviewed:
        clauses.append("reviewed=0")
    if flt.sections:
        marks = ",".join("?" * len(flt.sections))
        clauses.append(
            "id IN (SELECT x.item_id FROM item_sections x "
            f"JOIN sections s ON s.id=x.section_id WHERE s.slug IN ({marks}))"
        )
        params.extend(flt.sections)
    return " AND ".join(clauses), params


def query(db: Database, flt: ItemFilter | None = None, *, offset: int = 0, limit: int = 50) -> Page:
    """Items the filter covers, done ones last, newest first within a group."""
    where, params = _where(flt or ItemFilter())
    with db.session(readonly=True) as conn:
        total = int(conn.execute(f"SELECT COUNT(*) FROM items WHERE {where}", params).fetchone()[0])
        rows = conn.execute(
            f"SELECT * FROM items WHERE {where} "
            "ORDER BY CASE status WHEN 'done' THEN 1 ELSE 0 END, created_at DESC, id DESC "
            "LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        return Page(items=[_row_to_item(conn, row) for row in rows], total=total)


def edit_item(
    db: Database,
    item_id: int,
    *,
    sections: Sequence[str] | None = None,
    status: Status | None = None,
    placement: Placement | None = None,
    text: str | None = None,
    reviewed: bool = True,
    now: datetime | None = None,
) -> Item | None:
    """Apply one Owner edit in a transaction; any edit marks the Item Reviewed. None if missing."""
    with db.session() as conn:
        row = conn.execute("SELECT placement FROM items WHERE id=?", (item_id,)).fetchone()
        if row is None:
            return None
        if sections is not None:
            _replace_sections(conn, item_id, sections)
        if status is not None:
            conn.execute("UPDATE items SET status=? WHERE id=?", (status, item_id))
        if text is not None:
            conn.execute("UPDATE items SET text=? WHERE id=?", (text, item_id))
        if placement is not None and placement != row["placement"]:
            _set_placement(conn, item_id, placement, now)
        conn.execute(
            "UPDATE items SET reviewed=?, updated_at=? WHERE id=?",
            (int(reviewed), stamp(now), item_id),
        )
        return _fetch(conn, item_id)


def delete_trashed(db: Database, item_id: int) -> bool:
    """Delete a trashed Item for good; False if it does not exist, ValueError if not trashed."""
    with db.session() as conn:
        # One statement, so a Capture restoring this Link cannot slip in between check and delete.
        if conn.execute(
            "DELETE FROM items WHERE id=? AND placement='trashed'", (item_id,)
        ).rowcount:
            return True
        if conn.execute("SELECT 1 FROM items WHERE id=?", (item_id,)).fetchone() is None:
            return False
        raise ValueError("only a trashed Item can be deleted")


def archive_done(db: Database, *, now: datetime | None = None) -> int:
    """Archive every active Item that is done; returns how many moved."""
    with db.session() as conn:
        cur = conn.execute(
            "UPDATE items SET placement='archived', trashed_at=NULL, updated_at=? "
            "WHERE placement='active' AND status='done'",
            (stamp(now),),
        )
        return cur.rowcount


def mark_reviewed(db: Database, flt: ItemFilter, *, now: datetime | None = None) -> int:
    """Mark every Item the filter covers (all pages) as Reviewed; returns how many changed."""
    where, params = _where(flt)
    with db.session() as conn:
        cur = conn.execute(
            f"UPDATE items SET reviewed=1, updated_at=? WHERE reviewed=0 AND {where}",
            [stamp(now), *params],
        )
        return cur.rowcount


def empty_trash(db: Database) -> int:
    """Delete every trashed Item for good; returns how many."""
    with db.session() as conn:
        return conn.execute("DELETE FROM items WHERE placement='trashed'").rowcount
