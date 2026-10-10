"""The notes runtime in the bot: the store, the Classifier, and the background passes (sweeper, show, reminders, thumbnails)."""

from __future__ import annotations

import asyncio
import io
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import aiohttp
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest

from notes.classify import make_classifier
from notes.classify.port import Classifier
from notes.db import Database
from notes.domain import items, reminders
from notes.domain.reminders import Notice, Notify
from notes.enrich import thumbnail
from notes.enrich.http import AiohttpClient, HttpClient
from notes.enrich.pipeline import enrich_item
from notes.enrich.voice import Download, VoiceRejected, VoiceUnavailable
from notes.sweeper import run_sweeper
from shared.config import settings
from shared.obs import get_logger

from . import notes_ui

log = get_logger(__name__)

# The Bot API refuses getFile above this; a longer Voice cannot be transcribed.
TELEGRAM_DOWNLOAD_MAX = 20 * 1024 * 1024
SHOW_POLL_S = 2
REMIND_POLL_S = 30


@dataclass
class NotesRuntime:
    db: Database
    http: HttpClient
    classifier: Classifier
    # Held so background enrichments are not garbage collected mid-flight.
    tasks: set[asyncio.Task[Any]] = field(default_factory=set)

    def spawn(self, coroutine: Coroutine[Any, Any, Any]) -> None:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def notify_for(self, bot: Bot) -> Notify:
        """What Enrichment tells the chat: the reaction, and the Due line when the domain says so."""

        async def notify(notice: Notice) -> None:
            await notes_ui.acknowledge(bot, notice.item)
            if notice.due is not None:
                await notes_ui.announce_due(bot, notice.item, notice.due)

        return notify

    def start_sweeper(self, bot: Bot) -> None:
        self.spawn(
            run_sweeper(
                self.db,
                http=self.http,
                classifier=self.classifier,
                notify=self.notify_for(bot),
                interval_s=max(settings.notes_enrich_sweep_seconds, 5),
                download=telegram_download(bot),
            )
        )

    def start_thumb_backfill(self) -> None:
        """Give Items without a Thumbnail one, once per start: a deploy or a restored Backup heals itself."""
        self.spawn(self._thumb_backfill())

    async def _thumb_backfill(self) -> None:
        try:
            counts = await thumbnail.backfill(self.db, self.http)
        except Exception:
            log.exception("notes: thumbnail backfill failed")
            return
        log.info("notes: thumbnail backfill %s", counts)

    def start_show_loop(self, bot: Bot) -> None:
        self.spawn(self._show_loop(bot))

    async def _show_loop(self, bot: Bot) -> None:
        """Serve the Mini App's «Открыть в чате» requests; the database is the queue (ADR-0008)."""
        while True:
            try:
                for item in await asyncio.to_thread(items.claim_show_requests, self.db):
                    await notes_ui.show_in_chat(bot, item)
            except Exception:
                log.exception("notes: show-in-chat pass failed; will try again")
            await asyncio.sleep(SHOW_POLL_S)

    def start_reminder_loop(self, bot: Bot) -> None:
        self.spawn(self._reminder_loop(bot))

    async def _reminder_loop(self, bot: Bot) -> None:
        """Hand todo Reminders back at their Due; the database is the queue (ADR-0011)."""
        while True:
            try:
                await self.remind_once(bot)
            except Exception:
                log.exception("notes: reminder pass failed; will try again")
            await asyncio.sleep(REMIND_POLL_S)

    async def remind_once(self, bot: Bot, now: datetime | None = None) -> int:
        """One reminder pass at `now`: claim every due Reminder and send it; returns how many."""
        due = await asyncio.to_thread(reminders.claim_due, self.db, now=now)
        for item in due:
            try:
                sent = await notes_ui.send_reminder(bot, item)
            except Exception:
                log.exception("notes: reminder for item %s failed", item.id)
                sent = False
            if not sent:
                await asyncio.to_thread(reminders.release, self.db, item)
        return len(due)

    def enrich_later(self, bot: Bot, item_id: int) -> None:
        self.spawn(
            enrich_item(
                self.db,
                item_id,
                http=self.http,
                classifier=self.classifier,
                notify=self.notify_for(bot),
                download=telegram_download(bot),
            )
        )


def telegram_download(bot: Bot) -> Download:
    """A Voice's bytes from Telegram, failures sorted into retry-later and give-up."""

    async def download(file_id: str) -> bytes:
        try:
            file = await bot.get_file(file_id)
            if (file.file_size or 0) > TELEGRAM_DOWNLOAD_MAX:
                raise VoiceRejected("over Telegram's 20 MB download limit")
            if not file.file_path:
                raise VoiceRejected("Telegram gave no file path")
            buffer = io.BytesIO()
            await bot.download_file(file.file_path, destination=buffer)
        except TelegramBadRequest as exc:  # "file is too big", a dead file_id
            raise VoiceRejected(str(exc)) from exc
        except TelegramAPIError as exc:
            raise VoiceUnavailable(str(exc)) from exc
        except aiohttp.ClientError as exc:  # its text embeds the download URL, which has the token
            raise VoiceUnavailable(f"download failed: {exc.__class__.__name__}") from None
        except TimeoutError:
            raise VoiceUnavailable("download timed out") from None
        return buffer.getvalue()

    return download


def build_runtime() -> NotesRuntime:
    db = Database(settings.notes_db_path)
    db.init()
    return NotesRuntime(db=db, http=AiohttpClient(), classifier=make_classifier(settings))
