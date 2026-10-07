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
from notes.domain import items, sections, settings
from notes.domain.items import Item
from notes.enrich.http import FetchError, HttpClient
from notes.enrich.providers import Fetched, bare_host, fetch_for, is_youtube, youtube
from notes.enrich.voice import Download, VoiceRejected, VoiceUnavailable, transcript_for
from shared.obs import get_logger

log = get_logger(__name__)

# Called with the stored Item once Enrichment lands; the flag: this Enrichment filled its Due.
Notify = Callable[[Item, bool], Awaitable[None]]


def build_request(
    item: Item,
    fetched: Fetched | None,
    known: list[sections.Section],
    image: tuple[bytes, str] | None = None,
    transcript: str | None = None,
    zone_name: str = "UTC",
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
        sender=item.sender,
        transcript=transcript,
        now_local=items.local_clock(item.created_at, zone_name),
        zone=zone_name,
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


# Item ids being enriched in this process: a slow Voice can outlive STALE_PENDING, and the
# sweeper must not start it a second time and pay for STT twice.
_in_flight: set[int] = set()


async def enrich_item(
    db: Database,
    item_id: int,
    *,
    http: HttpClient,
    classifier: Classifier,
    notify: Notify | None,
    download: Download | None = None,
    now: datetime | None = None,
) -> None:
    if item_id in _in_flight:
        return
    _in_flight.add(item_id)
    try:
        await _enrich_item(
            db, item_id, http=http, classifier=classifier, notify=notify, download=download, now=now
        )
    finally:
        _in_flight.discard(item_id)


async def _enrich_item(
    db: Database,
    item_id: int,
    *,
    http: HttpClient,
    classifier: Classifier,
    notify: Notify | None,
    download: Download | None,
    now: datetime | None,
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

    transcript = item.transcript
    if item.kind == "voice" and transcript is None:
        if download is None:
            log.info("item %s: no download wired in, Voice left pending", item.id)
            return
        try:
            transcript = await transcript_for(item, download)
            await asyncio.to_thread(items.store_transcript, db, item.id, transcript)
        except VoiceRejected as exc:
            log.warning("item %s: cannot transcribe: %s", item.id, exc)
            await _record_failure(items.mark_failed, db, item.id, str(exc), now, notify)
            return
        except VoiceUnavailable as exc:
            log.warning("item %s: transcription unavailable, will retry: %s", item.id, exc)
            await _record_failure(items.schedule_retry, db, item.id, str(exc), now, notify)
            return
        except KeyError:
            log.info("item %s was deleted while it was being transcribed", item.id)
            return
        except Exception as exc:
            log.exception("item %s: transcription failed, will retry", item.id)
            error = str(exc) or exc.__class__.__name__
            await _record_failure(items.schedule_retry, db, item.id, error, now, notify)
            return

    image: tuple[bytes, str] | None = None
    if item.kind in ("file", "voice"):
        image = await asyncio.to_thread(items.get_preview, db, item.id)
    elif fetched is not None:
        image = await load_image(http, fetched.image_url)
    known = await asyncio.to_thread(sections.list_sections, db)
    zone_name = await asyncio.to_thread(settings.get_zone, db)
    request = build_request(item, fetched, known, image, transcript, zone_name)
    try:
        filing = await file_with_fallback(classifier, request, http)
    except ClassifierRefused as exc:
        log.warning("item %s: classifier refused: %s", item.id, exc)
        updated = await _store_async(db, item, fetched, None, f"refused: {exc}", now, zone_name)
    except ClassifierRejected as exc:
        log.error("item %s: classifier rejected the request: %s", item.id, exc)
        await _record_failure(items.mark_failed, db, item.id, str(exc), now, notify)
        return
    except ClassifierUnavailable as exc:
        log.warning("item %s: classifier unavailable, will retry: %s", item.id, exc)
        await _record_failure(items.schedule_retry, db, item.id, str(exc), now, notify)
        return
    except Exception as exc:
        log.exception("item %s: enrichment failed, will retry", item.id)
        await _record_failure(items.schedule_retry, db, item.id, str(exc), now, notify)
        return
    else:
        updated = await _store_async(db, item, fetched, filing, fetch_error, now, zone_name)
    if updated is not None and notify is not None:
        await notify(updated, _filled_due(item, updated, filing, zone_name))


async def _record_failure(
    record: Callable[..., Item],
    db: Database,
    item_id: int,
    error: str,
    now: datetime | None,
    notify: Notify | None,
) -> None:
    """Record a failure; once it is final, tell the interface so the Acknowledgement stops waiting."""
    try:
        updated = await asyncio.to_thread(record, db, item_id, error, now=now)
    except KeyError:  # the Owner deleted it meanwhile
        log.info("item %s was deleted while it was being enriched", item_id)
        return
    if updated.enrichment_status == "failed" and notify is not None:
        await notify(updated, False)


def _due_of(item: Item, filing: Filing | None, zone_name: str) -> datetime | None:
    """The Filing's Due as UTC; one that is not after the Capture moment is a misread and dropped."""
    if filing is None or filing.due is None:
        return None
    due = items.local_to_utc(filing.due, zone_name)
    return due if items.stamp(due) > item.created_at else None


def _filled_due(item: Item, updated: Item, filing: Filing | None, zone_name: str) -> bool:
    due = _due_of(item, filing, zone_name)
    return due is not None and item.due_at is None and updated.due_at == items.stamp(due)


async def _store_async(
    db: Database,
    item: Item,
    fetched: Fetched | None,
    filing: Filing | None,
    error: str | None,
    now: datetime | None,
    zone_name: str,
) -> Item | None:
    try:
        return await asyncio.to_thread(_store, db, item, fetched, filing, error, now, zone_name)
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
    zone_name: str,
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
        due=_due_of(item, filing, zone_name),
        now=now,
    )
