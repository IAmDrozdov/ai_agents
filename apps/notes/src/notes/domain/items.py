"""Items: Links, Notes, Files and Voices, their Filing and Status (ADR-0001, ADR-0002, ADR-0010)."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from notes.db import Database, fold
from notes.domain.sections import OTHER_SLUG, Section, _row_to_section, other_id
from notes.domain.urls import normalize_url

Kind = Literal["link", "note", "file", "voice"]
Status = Literal["todo", "done"]
EnrichmentStatus = Literal["pending", "done", "failed", "skipped"]
CaptureOutcome = Literal["new", "existing"]
DayField = Literal["captured", "done"]
DAY_COLUMNS: dict[DayField, str] = {"captured": "created_at", "done": "done_at"}
# Search reads every text field but the URL ("com" would match every Link).
SEARCH_COLUMNS = (
    "title", "gist", "text", "caption", "transcript", "author", "sender", "source", "file_name",
)  # fmt: skip

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
    created_at: str
    updated_at: str
    sections: tuple[Section, ...]


@dataclass(frozen=True)
class Capture:
    """What a Capture produced: a fresh Item, or the one this link already had."""

    item: Item
    outcome: CaptureOutcome


@dataclass(frozen=True)
class ItemFilter:
    """Which Items a list covers: one Status (both if None), any listed Section, a local day, a Search text."""

    sections: tuple[str, ...] = ()
    status: Status | None = "todo"
    day: date | None = None
    day_field: DayField = "captured"
    tz: str = "UTC"
    text: str = ""


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
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        sections=_sections_of(conn, int(row["id"])),
    )


def _fetch(conn: sqlite3.Connection, item_id: int) -> Item:
    row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if row is None:
        raise KeyError(item_id)
    return _row_to_item(conn, row)


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
            (text, sender, chat_id, message_id, stamp(now), stamp(now)),
        )
        item_id = int(cur.lastrowid or 0)
        conn.execute(
            "INSERT INTO item_sections(item_id, section_id) VALUES (?, ?)",
            (item_id, other_id(db)),
        )
        return _fetch(conn, item_id)


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
                stamp(now),
                stamp(now),
            ),
        )
        item_id = int(cur.lastrowid or 0)
        _file_in_other(conn, db, item_id, preview)
        return _fetch(conn, item_id)


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
                stamp(now),
                stamp(now),
            ),
        )
        item_id = int(cur.lastrowid or 0)
        _file_in_other(conn, db, item_id, preview)
        return _fetch(conn, item_id)


def _file_in_other(
    conn: sqlite3.Connection, db: Database, item_id: int, preview: tuple[bytes, str] | None
) -> None:
    conn.execute(
        "INSERT INTO item_sections(item_id, section_id) VALUES (?, ?)", (item_id, other_id(db))
    )
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
            (url, key, annotation, sender, chat_id, message_id, stamp(now), stamp(now)),
        )
        if cur.rowcount == 1:
            item_id = int(cur.lastrowid or 0)
            conn.execute(
                "INSERT INTO item_sections(item_id, section_id) VALUES (?, ?)",
                (item_id, other_id(db)),
            )
            return Capture(_fetch(conn, item_id), "new")
        row = conn.execute("SELECT * FROM items WHERE url_normalized=?", (key,)).fetchone()
        return Capture(_row_to_item(conn, row), "existing")


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


def _in_other_alone(conn: sqlite3.Connection, item_id: int) -> bool:
    rows = conn.execute(
        "SELECT s.slug FROM item_sections x JOIN sections s ON s.id = x.section_id "
        "WHERE x.item_id=?",
        (item_id,),
    ).fetchall()
    return [row["slug"] for row in rows] in ([], [OTHER_SLUG])


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
            (title, source, author, caption, image_url, gist, error, stamp(now), item_id),
        )
        if cur.rowcount == 0:
            raise KeyError(item_id)
        if _in_other_alone(conn, item_id):
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
            "enrichment_error=NULL, next_enrich_at=?, updated_at=?, "
            "transcript=CASE WHEN kind='voice' THEN NULL ELSE transcript END WHERE id=?",
            (stamp(now), stamp(now), item_id),
        )
        return _fetch(conn, item_id)


def store_transcript(db: Database, item_id: int, text: str) -> None:
    """Keep a Voice's Transcript as soon as STT lands, so a Classifier retry does not pay for it again."""
    with db.session() as conn:
        cur = conn.execute("UPDATE items SET transcript=? WHERE id=?", (text, item_id))
        if cur.rowcount == 0:
            raise KeyError(item_id)


def request_show(db: Database, item_id: int, *, now: datetime | None = None) -> Item | None:
    """Ask the bot to point at the Item's original message in the chat; None if missing."""
    with db.session() as conn:
        conn.execute("UPDATE items SET show_requested_at=? WHERE id=?", (stamp(now), item_id))
        try:
            return _fetch(conn, item_id)
        except KeyError:
            return None


def claim_show_requests(db: Database) -> list[Item]:
    """Every pending show request, cleared by the same statement so each is served once."""
    with db.session() as conn:
        rows = conn.execute(
            "UPDATE items SET show_requested_at=NULL WHERE show_requested_at IS NOT NULL "
            "RETURNING id"
        ).fetchall()
        return [_fetch(conn, int(row["id"])) for row in rows]


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


def zone(name: str) -> tzinfo:
    """The named IANA zone, or UTC when it is unknown."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return UTC


def local_midnight_utc(day: date, tz: str) -> str:
    """The UTC timestamp at which `day` starts in zone `tz`."""
    start = datetime(day.year, day.month, day.day, tzinfo=zone(tz))
    return stamp(start)


def _where(flt: ItemFilter) -> tuple[str, list[object]]:
    clauses = ["1"]
    params: list[object] = []
    if flt.status is not None:
        clauses.append("status=?")
        params.append(flt.status)
    needle = fold(flt.text.strip())
    if needle:
        clauses.append("(" + " OR ".join(f"instr(fold({c}), ?) > 0" for c in SEARCH_COLUMNS) + ")")
        params.extend([needle] * len(SEARCH_COLUMNS))
    if flt.sections:
        marks = ",".join("?" * len(flt.sections))
        clauses.append(
            "id IN (SELECT x.item_id FROM item_sections x "
            f"JOIN sections s ON s.id=x.section_id WHERE s.slug IN ({marks}))"
        )
        params.extend(flt.sections)
    if flt.day is not None:
        column = DAY_COLUMNS[flt.day_field]
        clauses.append(f"{column} >= ? AND {column} < ?")
        params.extend(
            [
                local_midnight_utc(flt.day, flt.tz),
                local_midnight_utc(flt.day + timedelta(1), flt.tz),
            ]
        )
    return " AND ".join(clauses), params


def query(db: Database, flt: ItemFilter | None = None, *, offset: int = 0, limit: int = 50) -> Page:
    """Items the filter covers, newest first."""
    where, params = _where(flt or ItemFilter())
    with db.session(readonly=True) as conn:
        total = int(conn.execute(f"SELECT COUNT(*) FROM items WHERE {where}", params).fetchone()[0])
        rows = conn.execute(
            f"SELECT * FROM items WHERE {where} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
        return Page(items=[_row_to_item(conn, row) for row in rows], total=total)


def edit_item(
    db: Database,
    item_id: int,
    *,
    sections: Sequence[str] | None = None,
    status: Status | None = None,
    text: str | None = None,
    now: datetime | None = None,
) -> Item | None:
    """Apply one Owner edit in a transaction; `done_at` follows Status. None if missing."""
    with db.session() as conn:
        row = conn.execute("SELECT status FROM items WHERE id=?", (item_id,)).fetchone()
        if row is None:
            return None
        if sections is not None:
            _replace_sections(conn, item_id, sections)
        if status is not None and status != row["status"]:
            done_at = stamp(now) if status == "done" else None
            conn.execute(
                "UPDATE items SET status=?, done_at=? WHERE id=?", (status, done_at, item_id)
            )
        if text is not None:
            conn.execute("UPDATE items SET text=? WHERE id=?", (text, item_id))
        conn.execute("UPDATE items SET updated_at=? WHERE id=?", (stamp(now), item_id))
        return _fetch(conn, item_id)


def delete_item(db: Database, item_id: int) -> bool:
    """Delete an Item for good, with its Filing and preview; False if it does not exist."""
    with db.session() as conn:
        return conn.execute("DELETE FROM items WHERE id=?", (item_id,)).rowcount > 0
