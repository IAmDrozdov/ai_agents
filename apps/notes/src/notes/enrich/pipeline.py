"""Enrich one pending Item: fetch (best effort) → classify → store → notify the interface."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime

from notes.classify.port import (
    Classifier,
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
from notes.enrich.providers import Fetched, bare_host, fetch_for
from shared.obs import get_logger

log = get_logger(__name__)

# Called with the stored Item once Enrichment lands, e.g. to edit the Acknowledgement.
Notify = Callable[[Item], Awaitable[None]]


def build_request(
    item: Item, fetched: Fetched | None, known: list[sections.Section]
) -> FilingRequest:
    return FilingRequest(
        kind=item.kind,
        url=item.url,
        source=fetched.source if fetched else None,
        title=fetched.title if fetched else None,
        author=fetched.author if fetched else None,
        caption=fetched.caption if fetched else None,
        annotation=item.text,
        sections=[SectionBrief(slug=s.slug, name=s.name, hint=s.hint) for s in known],
    )


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

    known = await asyncio.to_thread(sections.list_sections, db)
    request = build_request(item, fetched, known)
    try:
        filing = await classifier.file(request)
    except ClassifierRefused as exc:
        log.warning("item %s: classifier refused: %s", item.id, exc)
        updated = await asyncio.to_thread(_store, db, item, fetched, None, f"refused: {exc}", now)
    except ClassifierRejected as exc:
        log.error("item %s: classifier rejected the request: %s", item.id, exc)
        await asyncio.to_thread(items.mark_failed, db, item.id, str(exc), now=now)
        return
    except ClassifierUnavailable as exc:
        log.warning("item %s: classifier unavailable, will retry: %s", item.id, exc)
        await asyncio.to_thread(items.schedule_retry, db, item.id, str(exc), now=now)
        return
    except Exception as exc:
        log.exception("item %s: enrichment failed, will retry", item.id)
        await asyncio.to_thread(items.schedule_retry, db, item.id, str(exc), now=now)
        return
    else:
        updated = await asyncio.to_thread(_store, db, item, fetched, filing, fetch_error, now)
    if notify is not None:
        await notify(updated)


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
