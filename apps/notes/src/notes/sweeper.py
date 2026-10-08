"""Housekeeping loop run by the bot process: due Enrichment (retries, restart leftovers)."""

from __future__ import annotations

import asyncio
from datetime import datetime

from notes.classify.port import Classifier
from notes.db import Database
from notes.domain import items
from notes.enrich.http import HttpClient
from notes.enrich.pipeline import Notify, enrich_item
from notes.enrich.voice import Download
from shared.obs import get_logger

log = get_logger(__name__)


async def sweep_once(
    db: Database,
    *,
    http: HttpClient,
    classifier: Classifier,
    notify: Notify,
    download: Download,
    now: datetime | None = None,
) -> int:
    """Enrich everything that is due; returns how many Items were picked up."""
    due = await asyncio.to_thread(items.claim_due_enrichments, db, now=now)
    for item_id in due:
        try:
            await enrich_item(
                db,
                item_id,
                http=http,
                classifier=classifier,
                notify=notify,
                download=download,
                now=now,
            )
        except Exception:
            log.exception("sweep: item %s failed; moving on", item_id)
    return len(due)


async def run_sweeper(
    db: Database,
    *,
    http: HttpClient,
    classifier: Classifier,
    notify: Notify,
    interval_s: int,
    download: Download,
) -> None:
    while True:
        try:
            picked = await sweep_once(
                db, http=http, classifier=classifier, notify=notify, download=download
            )
            if picked:
                log.info("sweep: enriched %d item(s)", picked)
        except Exception:
            log.exception("sweep failed; will try again next interval")
        await asyncio.sleep(interval_s)
