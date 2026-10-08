"""Items: Links, Notes, Files and Voices, their Status and Due; the Filing is `sections`."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum, auto
from typing import Literal

from notes.db import Database
from notes.domain import clock
from notes.domain.sections import (
    Section,
    file_in_other,
    filing_of,
    filings_of,
    in_other_alone,
    refile,
)
from notes.domain.urls import normalize_url

Kind = Literal["link", "note", "file", "voice"]
Status = Literal["todo", "done"]
EnrichmentStatus = Literal["pending", "done", "failed", "skipped"]
CaptureOutcome = Literal["new", "existing"]
ITEM_SELECT = (
    "SELECT items.*, (SELECT etag FROM item_thumbs WHERE item_id = items.id) AS thumb FROM items"
)
BACKOFF = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=12),
)
STALE_PENDING = timedelta(minutes=2)


class Unset(Enum):
    UNSET = auto()


UNSET = Unset.UNSET


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
    file_id: str | None
    file_name: str | None
    file_mime: str | None
    file_size: int | None
    duration_s: int | None
    transcript: str | None
    sender: str | None
    status: Status
    done_at: str | None
    enrichment_status: EnrichmentStatus
    enrichment_attempts: int
    enrichment_error: str | None
    next_enrich_at: str | None
    tg_chat_id: int | None
    tg_ack_message_id: int | None
    tg_message_id: int | None
    show_requested_at: str | None
    due_at: str | None
    reminded_at: str | None
    created_at: str
    updated_at: str
    sections: tuple[Section, ...]
    thumb: str | None = None  # the stored Thumbnail's etag


@dataclass(frozen=True)
class Capture:
    """What a Capture produced: a fresh Item, or the one this link already had."""

    item: Item
    outcome: CaptureOutcome


def row_to_item(row: sqlite3.Row, filing: tuple[Section, ...]) -> Item:
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
        file_id=row["file_id"],
        file_name=row["file_name"],
        file_mime=row["file_mime"],
        file_size=row["file_size"],
        duration_s=row["duration_s"],
        transcript=row["transcript"],
        sender=row["sender"],
        status=row["status"],
        done_at=row["done_at"],
        enrichment_status=row["enrichment_status"],
        enrichment_attempts=int(row["enrichment_attempts"]),
        enrichment_error=row["enrichment_error"],
        next_enrich_at=row["next_enrich_at"],
        tg_chat_id=row["tg_chat_id"],
        tg_ack_message_id=row["tg_ack_message_id"],
        tg_message_id=row["tg_message_id"],
        show_requested_at=row["show_requested_at"],
        due_at=row["due_at"],
        reminded_at=row["reminded_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        sections=filing,
        thumb=row["thumb"],
    )


def fetch(conn: sqlite3.Connection, item_id: int) -> Item:
    """One Item on an open connection; KeyError if missing."""
    row = conn.execute(f"{ITEM_SELECT} WHERE id=?", (item_id,)).fetchone()
    if row is None:
        raise KeyError(item_id)
    return row_to_item(row, filing_of(conn, item_id))


def rows_to_items(conn: sqlite3.Connection, rows: Sequence[sqlite3.Row]) -> list[Item]:
    """Items for ITEM_SELECT rows, their Filings loaded in one read."""
    filings = filings_of(conn, [int(row["id"]) for row in rows])
    return [row_to_item(row, filings.get(int(row["id"]), ())) for row in rows]


def fetch_many(conn: sqlite3.Connection, item_ids: Sequence[int]) -> list[Item]:
    """The named Items that exist, by id."""
    marks = ",".join("?" * len(item_ids))
    rows = conn.execute(
        f"{ITEM_SELECT} WHERE id IN ({marks}) ORDER BY id", list(item_ids)
    ).fetchall()
    return rows_to_items(conn, rows)


def capture_note(
    db: Database,
    text: str,
    *,
    sender: str | None = None,
    chat_id: int | None = None,
    message_id: int | None = None,
    now: datetime | None = None,
) -> Item:
    """Save a Note; it lands in Other until the Classifier files it (ADR-0006)."""
    with db.session() as conn:
        cur = conn.execute(
            "INSERT INTO items(kind, text, sender, tg_chat_id, tg_message_id, created_at, updated_at) "
            "VALUES ('note', ?, ?, ?, ?, ?, ?)",
            (text, sender, chat_id, message_id, clock.stamp(now), clock.stamp(now)),
        )
        item_id = int(cur.lastrowid or 0)
        file_in_other(conn, item_id)
        return fetch(conn, item_id)


def capture_file(
    db: Database,
    *,
    file_id: str,
    file_name: str | None,
    file_mime: str | None,
    file_size: int | None,
    annotation: str,
    preview: tuple[bytes, str] | None,
    sender: str | None = None,
    chat_id: int | None = None,
    message_id: int | None = None,
    now: datetime | None = None,
) -> Item:
    """Save a File (photo, video, other document): Telegram keeps the bytes, we keep a preview."""
    with db.session() as conn:
        cur = conn.execute(
            "INSERT INTO items(kind, text, file_id, file_name, file_mime, file_size, sender, "
            "tg_chat_id, tg_message_id, created_at, updated_at) "
            "VALUES ('file', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                annotation,
                file_id,
                file_name,
                file_mime,
                file_size,
                sender,
                chat_id,
                message_id,
                clock.stamp(now),
                clock.stamp(now),
            ),
        )
        item_id = int(cur.lastrowid or 0)
        file_in_other(conn, item_id)
        _keep_preview(conn, item_id, preview)
        return fetch(conn, item_id)


def capture_voice(
    db: Database,
    *,
    file_id: str,
    file_mime: str | None,
    file_size: int | None,
    duration_s: int | None,
    annotation: str,
    preview: tuple[bytes, str] | None,
    sender: str | None = None,
    chat_id: int | None = None,
    message_id: int | None = None,
    now: datetime | None = None,
) -> Item:
    """Save a Voice (voice or round video message); Enrichment adds the Transcript."""
    with db.session() as conn:
        cur = conn.execute(
            "INSERT INTO items(kind, text, file_id, file_mime, file_size, duration_s, sender, "
            "tg_chat_id, tg_message_id, created_at, updated_at) "
            "VALUES ('voice', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                annotation,
                file_id,
                file_mime,
                file_size,
                duration_s,
                sender,
                chat_id,
                message_id,
                clock.stamp(now),
                clock.stamp(now),
            ),
        )
        item_id = int(cur.lastrowid or 0)
        file_in_other(conn, item_id)
        _keep_preview(conn, item_id, preview)
        return fetch(conn, item_id)


def _keep_preview(
    conn: sqlite3.Connection, item_id: int, preview: tuple[bytes, str] | None
) -> None:
    if preview is not None:
        conn.execute(
            "INSERT INTO item_previews(item_id, mime, data) VALUES (?, ?, ?)",
            (item_id, preview[1], preview[0]),
        )


def get_preview(db: Database, item_id: int) -> tuple[bytes, str] | None:
    """The stored preview image of a File or Voice as (bytes, mime), or None."""
    with db.session(readonly=True) as conn:
        row = conn.execute(
            "SELECT data, mime FROM item_previews WHERE item_id=?", (item_id,)
        ).fetchone()
    return (bytes(row["data"]), row["mime"]) if row else None


def store_thumb(db: Database, item_id: int, data: bytes, mime: str) -> bool:
    """Keep the Item's Thumbnail, replacing an older one; False if the Item is gone."""
    etag = hashlib.sha256(data).hexdigest()[:16]
    with db.session() as conn:
        # One statement: an Item deleted meanwhile simply matches nothing.
        return (
            conn.execute(
                "INSERT INTO item_thumbs(item_id, mime, etag, data) "
                "SELECT id, ?, ?, ? FROM items WHERE id=? "
                "ON CONFLICT(item_id) DO UPDATE SET mime=excluded.mime, etag=excluded.etag, "
                "data=excluded.data",
                (mime, etag, data, item_id),
            ).rowcount
            > 0
        )


def get_thumb(db: Database, item_id: int) -> tuple[bytes, str, str] | None:
    """The Item's Thumbnail as (bytes, mime, etag), or None."""
    with db.session(readonly=True) as conn:
        row = conn.execute(
            "SELECT data, mime, etag FROM item_thumbs WHERE item_id=?", (item_id,)
        ).fetchone()
    return (bytes(row["data"]), row["mime"], row["etag"]) if row else None


def missing_thumbs(db: Database) -> list[Item]:
    """Items that have no Thumbnail yet, oldest first."""
    with db.session(readonly=True) as conn:
        rows = conn.execute(
            f"{ITEM_SELECT} WHERE id NOT IN (SELECT item_id FROM item_thumbs) ORDER BY id"
        ).fetchall()
        return rows_to_items(conn, rows)


def capture_link(
    db: Database,
    url: str,
    annotation: str,
    *,
    sender: str | None = None,
    chat_id: int | None = None,
    message_id: int | None = None,
    now: datetime | None = None,
) -> Capture:
    """Save a Link once: a repeat returns the existing Item as it is, done or not (ADR-0010)."""
    key = normalize_url(url)
    with db.session() as conn:
        # OR IGNORE against the unique key makes a double-send race-free: the loser sees the row.
        cur = conn.execute(
            "INSERT OR IGNORE INTO items"
            "(kind, url, url_normalized, text, sender, tg_chat_id, tg_message_id, "
            "created_at, updated_at) VALUES ('link', ?, ?, ?, ?, ?, ?, ?, ?)",
            (url, key, annotation, sender, chat_id, message_id, clock.stamp(now), clock.stamp(now)),
        )
        if cur.rowcount == 1:
            item_id = int(cur.lastrowid or 0)
            file_in_other(conn, item_id)
            return Capture(fetch(conn, item_id), "new")
        row = conn.execute(f"{ITEM_SELECT} WHERE url_normalized=?", (key,)).fetchone()
        return Capture(row_to_item(row, filing_of(conn, int(row["id"]))), "existing")


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
    """Record what Enrichment found; the Classifier files the Item only while it is in Other alone.

    Raises KeyError if the Item was deleted while it was being enriched.
    """
    with db.session() as conn:
        cur = conn.execute(
            "UPDATE items SET title=?, source=?, author=?, caption=?, image_url=?, gist=?, "
            "enrichment_status='done', enrichment_error=?, next_enrich_at=NULL, updated_at=? "
            "WHERE id=?",
            (title, source, author, caption, image_url, gist, error, clock.stamp(now), item_id),
        )
        if cur.rowcount == 0:
            raise KeyError(item_id)
        if in_other_alone(conn, item_id):
            refile(conn, item_id, sections)
        return fetch(conn, item_id)


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
                (attempts, error, clock.stamp(now), item_id),
            )
        else:
            moment = (now or datetime.now(UTC)).astimezone(UTC)
            conn.execute(
                "UPDATE items SET enrichment_status='pending', enrichment_attempts=?, "
                "enrichment_error=?, next_enrich_at=?, updated_at=? WHERE id=?",
                (
                    attempts,
                    error,
                    clock.stamp(moment + BACKOFF[attempts - 1]),
                    clock.stamp(now),
                    item_id,
                ),
            )
        return fetch(conn, item_id)


def mark_failed(db: Database, item_id: int, error: str, *, now: datetime | None = None) -> Item:
    """Give up on Enrichment now; only a manual re-enrich brings the Item back."""
    with db.session() as conn:
        conn.execute(
            "UPDATE items SET enrichment_status='failed', enrichment_error=?, "
            "next_enrich_at=NULL, updated_at=? WHERE id=?",
            (error, clock.stamp(now), item_id),
        )
        return fetch(conn, item_id)


def request_reenrich(db: Database, item_id: int, *, now: datetime | None = None) -> Item:
    """Start Enrichment over, immediately due for the sweeper."""
    with db.session() as conn:
        conn.execute(
            "UPDATE items SET enrichment_status='pending', enrichment_attempts=0, "
            "enrichment_error=NULL, next_enrich_at=?, updated_at=?, "
            "transcript=CASE WHEN kind='voice' THEN NULL ELSE transcript END WHERE id=?",
            (clock.stamp(now), clock.stamp(now), item_id),
        )
        return fetch(conn, item_id)


def store_transcript(db: Database, item_id: int, text: str) -> None:
    """Keep a Voice's Transcript as soon as STT lands, so a Classifier retry does not pay for it again."""
    with db.session() as conn:
        cur = conn.execute("UPDATE items SET transcript=? WHERE id=?", (text, item_id))
        if cur.rowcount == 0:
            raise KeyError(item_id)


def request_show(db: Database, item_id: int, *, now: datetime | None = None) -> Item | None:
    """Ask the bot to point at the Item's original message in the chat; None if missing."""
    with db.session() as conn:
        conn.execute("UPDATE items SET show_requested_at=? WHERE id=?", (clock.stamp(now), item_id))
        try:
            return fetch(conn, item_id)
        except KeyError:
            return None


def claim_show_requests(db: Database) -> list[Item]:
    """Every pending show request, cleared by the same statement so each is served once."""
    with db.session() as conn:
        rows = conn.execute(
            "UPDATE items SET show_requested_at=NULL WHERE show_requested_at IS NOT NULL "
            "RETURNING id"
        ).fetchall()
        return fetch_many(conn, [int(row["id"]) for row in rows])


def claim_due_enrichments(db: Database, *, now: datetime | None = None) -> list[int]:
    """Scheduled retries whose time has come, plus pending Items nothing has touched lately."""
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    with db.session(readonly=True) as conn:
        rows = conn.execute(
            "SELECT id FROM items WHERE enrichment_status='pending' AND ("
            "(next_enrich_at IS NOT NULL AND next_enrich_at <= ?) OR "
            "(next_enrich_at IS NULL AND updated_at <= ?)) ORDER BY id",
            (clock.stamp(moment), clock.stamp(moment - STALE_PENDING)),
        ).fetchall()
    return [int(row["id"]) for row in rows]


def get_item(db: Database, item_id: int) -> Item | None:
    with db.session(readonly=True) as conn:
        try:
            return fetch(conn, item_id)
        except KeyError:
            return None


def edit_item(
    db: Database,
    item_id: int,
    *,
    sections: Sequence[str] | None = None,
    status: Status | None = None,
    text: str | None = None,
    due: datetime | None | Unset = UNSET,
    now: datetime | None = None,
) -> Item | None:
    """Apply one Owner edit in a transaction; `done_at` follows Status. None if missing.

    `due` sets or moves the Due (a future moment, else ValueError); None removes it (ADR-0011).
    """
    moment = (now or datetime.now(UTC)).astimezone(UTC)
    if isinstance(due, datetime) and due.astimezone(UTC) <= moment:
        raise ValueError("The Due must be in the future")
    with db.session() as conn:
        row = conn.execute("SELECT status FROM items WHERE id=?", (item_id,)).fetchone()
        if row is None:
            return None
        if sections is not None:
            refile(conn, item_id, sections)
        if isinstance(due, datetime):
            conn.execute(
                "UPDATE items SET due_at=?, reminded_at=NULL WHERE id=?",
                (clock.stamp(due), item_id),
            )
        elif due is None:
            conn.execute("UPDATE items SET due_at=NULL, reminded_at=NULL WHERE id=?", (item_id,))
        if status is not None and status != row["status"]:
            done_at = clock.stamp(moment) if status == "done" else None
            conn.execute(
                "UPDATE items SET status=?, done_at=? WHERE id=?", (status, done_at, item_id)
            )
            if status == "todo":  # a Due already past does not fire late (ADR-0011)
                conn.execute(
                    "UPDATE items SET reminded_at=? WHERE id=? AND due_at <= ? "
                    "AND reminded_at IS NULL",
                    (clock.stamp(moment), item_id, clock.stamp(moment)),
                )
        if text is not None:
            conn.execute("UPDATE items SET text=? WHERE id=?", (text, item_id))
        conn.execute("UPDATE items SET updated_at=? WHERE id=?", (clock.stamp(now), item_id))
        return fetch(conn, item_id)


def delete_item(db: Database, item_id: int) -> bool:
    """Delete an Item for good, with its Filing and preview; False if it does not exist."""
    with db.session() as conn:
        return conn.execute("DELETE FROM items WHERE id=?", (item_id,)).rowcount > 0
