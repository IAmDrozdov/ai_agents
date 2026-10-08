"""Capture: the Owner's message in, exactly one Item out, and what to acknowledge (ADR-0006, 0009, 0010, 0011)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from notes.classify.port import Classifier
from notes.db import Database
from notes.domain import items, reminders
from notes.domain.items import CaptureOutcome, Item
from notes.domain.urls import extract_urls
from shared.obs import get_logger

log = get_logger(__name__)

# Promises of capture():
# 1. Exactly one Item: Text with one URL is a Link, none or several a Note; an Attachment is a Voice
#    (speech) or a File. Notes, Files and Voices are always "new".
# 2. Dedupe: a Link whose normalised URL exists returns that Item untouched (Status kept, done included,
#    ADR-0010), except that non-empty words go through reminders.request_due.
# 3. Saved before it returns: the row is committed, in Other, pending (ADR-0006). enrich = "new".
# 4. Acknowledgement: new -> wait; existing -> look if Enrichment failed, else saved.
# 5. A store failure raises and nothing was saved. Once committed nothing raises: an unreadable Due is None.
# 6. Store calls run in threads, the Classifier (duplicates only) is awaited; no module-level state.
# 7. `now` pins created_at and the "is the Due ahead" check; default the current time.

# What the reaction on the Capture message should say: wait, it is in notes, take a look (CONTEXT: Acknowledgement).
Acknowledgement = Literal["wait", "saved", "look"]


@dataclass(frozen=True)
class Text:
    """The Owner's words and the links Telegram hides behind text: a text message or a 💾 Draft."""

    words: str
    links: tuple[str, ...] = ()


@dataclass(frozen=True)
class Attachment:
    """A photo, video, document, voice or round video: Telegram keeps the bytes, notes the facts (ADR-0007, 0008)."""

    file_id: str
    mime: str | None
    size: int | None
    caption: str = ""  # the Owner's words sent with it; becomes the Annotation
    file_name: str | None = None  # a document's name; None for a photo, voice or round video
    duration_s: int | None = None
    preview: tuple[bytes, str] | None = None  # Telegram's small preview as (bytes, mime)
    speech: bool = False  # True: a voice or round video; it becomes a Voice


Payload = Text | Attachment


@dataclass(frozen=True)
class Origin:
    """Where the Capture came from: the message its Acknowledgement goes on, and who forwarded it."""

    chat_id: int | None
    message_id: int | None
    sender: str | None = None


@dataclass(frozen=True)
class Captured:
    item: Item  # as stored after this Capture (a duplicate's new Due and Status applied)
    outcome: CaptureOutcome  # "new" | "existing"
    acknowledgement: Acknowledgement  # what the Capture message's reaction should say now
    due: (
        datetime | None
    )  # the Due this Capture's words put on an existing Item, in the Zone; tell the Owner
    enrich: bool  # the caller must start Enrichment of `item` (every new Item, never a duplicate)


async def capture(
    db: Database,
    payload: Payload,
    origin: Origin,
    *,
    classifier: Classifier,
    now: datetime | None = None,
) -> Captured:
    """One Capture becomes exactly one Item (ADR-0009); the promises are in the module docs."""
    where = {
        "sender": origin.sender,
        "chat_id": origin.chat_id,
        "message_id": origin.message_id,
        "now": now,
    }
    due: datetime | None = None
    if isinstance(payload, Attachment):
        if payload.speech:
            item = await asyncio.to_thread(
                items.capture_voice,
                db,
                file_id=payload.file_id,
                file_mime=payload.mime,
                file_size=payload.size,
                duration_s=payload.duration_s,
                annotation=payload.caption,
                preview=payload.preview,
                **where,
            )
            kind = "voice"
        else:
            item = await asyncio.to_thread(
                items.capture_file,
                db,
                file_id=payload.file_id,
                file_name=payload.file_name,
                file_mime=payload.mime,
                file_size=payload.size,
                annotation=payload.caption,
                preview=payload.preview,
                **where,
            )
            kind = "file"
        outcome: CaptureOutcome = "new"
    else:
        extracted = extract_urls(payload.words, linked=payload.links)
        if len(extracted.urls) == 1:
            kind = "link"
            got = await asyncio.to_thread(
                items.capture_link, db, extracted.urls[0], extracted.annotation, **where
            )
            item, outcome = got.item, got.outcome
            if outcome == "existing" and extracted.annotation.strip():
                notice = await reminders.request_due(
                    db, classifier, item, extracted.annotation, now=now
                )
                item, due = notice.item, notice.due
        else:
            kind = "note"
            item = await asyncio.to_thread(items.capture_note, db, payload.words, **where)
            outcome = "new"
    log.info("notes: capture %s %s → item %s", kind, outcome, item.id)
    acknowledgement: Acknowledgement = "wait"
    if (
        outcome == "existing"
    ):  # a still-pending duplicate says saved: it is in notes, the sweeper finishes it
        acknowledgement = "look" if item.enrichment_status == "failed" else "saved"
    return Captured(item, outcome, acknowledgement, due, enrich=outcome == "new")


def acknowledgement_of(item: Item) -> Acknowledgement:
    """What an Item's Enrichment state says to its Capture message: pending → wait, failed → look, else saved."""
    match item.enrichment_status:
        case "pending":
            return "wait"
        case "failed":
            return "look"
        case _:
            return "saved"
