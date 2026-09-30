"""Enrich one pending Item: fetch (best effort) → classify → store → notify the interface."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime

from notes.classify.port import (
    Classifier,
    ClassifierError,
    ClassifierRefused,
    ClassifierRejected,
    ClassifierUnavailable,
    Filing,
    FilingRequest,
    SectionBrief,
)
from notes.db import Database
from notes.domain import items, sections
from notes.domain.items import Item
from notes.enrich.http import FetchError, HttpClient
from notes.enrich.providers import Fetched, bare_host, fetch_for, is_youtube, youtube
from shared.obs import get_logger

log = get_logger(__name__)

# Called with the stored Item once Enrichment lands, e.g. to edit the Acknowledgement.
Notify = Callable[[Item], Awaitable[None]]


def build_request(
    item: Item,
    fetched: Fetched | None,
    known: list[sections.Section],
    image: tuple[bytes, str] | None = None,
) -> FilingRequest:
    return FilingRequest(
        kind=item.kind,
        url=item.url,
        file_name=item.file_name,
        image=image[0] if image else None,
        image_mime=image[1] if image else None,
        source=fetched.source if fetched else None,
        title=fetched.title if fetched else None,
        author=fetched.author if fetched else None,
        caption=fetched.caption if fetched else None,
        annotation=item.text,
        sections=[SectionBrief(slug=s.slug, name=s.name, hint=s.hint) for s in known],
    )


async def load_image(http: HttpClient, image_url: str | None) -> tuple[bytes, str] | None:
    """The cover image for vision, best effort: a missing or unreadable one just means no picture."""
    if not image_url or not image_url.lower().startswith(("http://", "https://")):
        return None
    try:
        return await http.get_image(image_url)
    except FetchError as exc:
        log.info("no cover image from %s: %s", image_url, exc)
        return None


async def file_with_fallback(
    classifier: Classifier, request: FilingRequest, http: HttpClient
) -> Filing:
    """Classify; if the model is unsure about a YouTube video, ask once more with its captions."""
    filing = await classifier.file(request)
    if filing.confident or not request.url or not is_youtube(request.url):
        return filing
    text = await youtube.transcript(request.url, http)
    if not text:
        return filing
    try:
        return await classifier.file(request.model_copy(update={"transcript": text}))
    except ClassifierError as exc:
        log.info("transcript pass failed, keeping the first filing: %s", exc)
        return filing


async def enrich_item(
    db: Database,
    item_id: int,
    *,
    http: HttpClient,
    classifier: Classifier,
    notify: Notify | None,
    now: datetime | None = None,
) -> None:
    item = await asyncio.to_thread(items.get_item, db, item_id)
    if item is None or item.enrichment_status != "pending":
        return

    fetched: Fetched | None = None
    fetch_error: str | None = None
    if item.kind == "link" and item.url:
        try:
            fetched = await fetch_for(item.url, http)
        except FetchError as exc:
            fetch_error = str(exc)
            log.info("item %s: could not fetch %s: %s", item.id, item.url, exc)
            fetched = Fetched(source=bare_host(item.url))
        except Exception as exc:
            fetch_error = f"{exc.__class__.__name__}: {exc}"
            log.exception("item %s: fetching %s failed unexpectedly", item.id, item.url)
            fetched = Fetched(source=bare_host(item.url))

    image: tuple[bytes, str] | None = None
    if item.kind == "file":
        image = await asyncio.to_thread(items.get_preview, db, item.id)
    elif fetched is not None:
        image = await load_image(http, fetched.image_url)
    known = await asyncio.to_thread(sections.list_sections, db)
    request = build_request(item, fetched, known, image)
    try:
        filing = await file_with_fallback(classifier, request, http)
    except ClassifierRefused as exc:
        log.warning("item %s: classifier refused: %s", item.id, exc)
        updated = await _store_async(db, item, fetched, None, f"refused: {exc}", now)
    except ClassifierRejected as exc:
        log.error("item %s: classifier rejected the request: %s", item.id, exc)
        await _record_failure(items.mark_failed, db, item.id, str(exc), now)
        return
    except ClassifierUnavailable as exc:
        log.warning("item %s: classifier unavailable, will retry: %s", item.id, exc)
        await _record_failure(items.schedule_retry, db, item.id, str(exc), now)
        return
    except Exception as exc:
        log.exception("item %s: enrichment failed, will retry", item.id)
        await _record_failure(items.schedule_retry, db, item.id, str(exc), now)
        return
    else:
        updated = await _store_async(db, item, fetched, filing, fetch_error, now)
    if updated is not None and notify is not None:
        await notify(updated)


async def _record_failure(
    record: Callable[..., Item], db: Database, item_id: int, error: str, now: datetime | None
) -> None:
    try:
        await asyncio.to_thread(record, db, item_id, error, now=now)
    except KeyError:  # the Owner deleted it meanwhile
        log.info("item %s was deleted while it was being enriched", item_id)


async def _store_async(
    db: Database,
    item: Item,
    fetched: Fetched | None,
    filing: Filing | None,
    error: str | None,
    now: datetime | None,
) -> Item | None:
    try:
        return await asyncio.to_thread(_store, db, item, fetched, filing, error, now)
    except KeyError:  # the Owner deleted it meanwhile
        log.info("item %s was deleted while it was being enriched", item.id)
        return None


def _store(
    db: Database,
    item: Item,
    fetched: Fetched | None,
    filing: Filing | None,
    error: str | None,
    now: datetime | None,
) -> Item:
    result = filing or Filing()
    return items.store_enrichment(
        db,
        item.id,
        sections=result.sections,
        gist=result.gist or None,
        title=result.title or (fetched.title if fetched else None),
        source=result.source or (fetched.source if fetched else None),
        author=result.author or (fetched.author if fetched else None),
        caption=fetched.caption if fetched else None,
        image_url=fetched.image_url if fetched else None,
        error=error,
        now=now,
    )
