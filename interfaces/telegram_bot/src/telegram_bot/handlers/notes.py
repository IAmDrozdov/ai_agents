"""Notes for the admin: 💾 on the card saves, then enriches in the background (ADR-015)."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from notes.classify import make_classifier
from notes.classify.port import Classifier
from notes.db import Database
from notes.domain import items
from notes.domain.items import Item
from notes.domain.urls import extract_urls
from notes.enrich.http import AiohttpClient, HttpClient
from notes.enrich.pipeline import enrich_item
from notes.sweeper import run_sweeper
from shared.config import settings
from shared.obs import get_logger

from .. import notes_ui
from ..access import is_admin
from ..keyboards import JobCB
from ..notes_ui import NotesCB
from .documents import Draft, offer_link, restore_draft, take_draft

log = get_logger(__name__)

router = Router(name="notes")


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

    def start_sweeper(self, bot: Bot) -> None:
        self.spawn(
            run_sweeper(
                self.db,
                http=self.http,
                classifier=self.classifier,
                notify=lambda item: notes_ui.edit_acknowledgement(bot, item),
                interval_s=max(settings.notes_enrich_sweep_seconds, 5),
            )
        )

    def enrich_later(self, bot: Bot, item_id: int) -> None:
        self.spawn(
            enrich_item(
                self.db,
                item_id,
                http=self.http,
                classifier=self.classifier,
                notify=lambda item: notes_ui.edit_acknowledgement(bot, item),
            )
        )


def build_runtime() -> NotesRuntime:
    db = Database(settings.notes_db_path)
    db.init()
    return NotesRuntime(db=db, http=AiohttpClient(), classifier=make_classifier(settings))


async def _save(card: Message, draft: Draft, bot: Bot, notes: NotesRuntime) -> None:
    """Turn the card into the first Item's Acknowledgement; further links get their own."""
    extracted = extract_urls(draft.text, linked=draft.links)
    captured: list[tuple[Item, str | None]] = []
    if not extracted.urls:
        note = await asyncio.to_thread(
            items.capture_note, notes.db, extracted.annotation, chat_id=card.chat.id
        )
        captured.append((note, None))
    for url in extracted.urls:
        capture = await asyncio.to_thread(
            items.capture_link, notes.db, url, extracted.annotation, chat_id=card.chat.id
        )
        is_new = capture.outcome == "new"
        captured.append((capture.item, None if is_new else notes_ui.duplicate(capture)))
    for index, (item, duplicate) in enumerate(captured):
        text = duplicate or notes_ui.acknowledgement(item)
        keyboard = notes_ui.item_keyboard(item)
        if index == 0:
            try:
                await card.edit_text(text, reply_markup=keyboard)
                sent = card
            except TelegramBadRequest:  # the card is gone: acknowledge in a new message
                sent = await card.answer(text, reply_markup=keyboard)
        else:
            sent = await card.answer(text, reply_markup=keyboard)
        if duplicate is None:
            await asyncio.to_thread(
                items.set_ack_message,
                notes.db,
                item.id,
                chat_id=sent.chat.id,
                message_id=sent.message_id,
            )
            notes.enrich_later(bot, item.id)


def _admin_message(callback: CallbackQuery) -> Message | None:
    if not is_admin(callback.from_user.id):
        return None
    return callback.message if isinstance(callback.message, Message) else None


@router.callback_query(JobCB.filter(F.action == "save"))
async def save_handler(callback: CallbackQuery, bot: Bot, notes: NotesRuntime | None) -> None:
    card = _admin_message(callback)
    if card is None or notes is None:
        await callback.answer("Notes are unavailable right now.", show_alert=True)
        return
    draft = take_draft(card.chat.id, card.message_id)
    if draft is None:
        await callback.answer("This card has expired — send it again.", show_alert=True)
        return
    try:
        await _save(card, draft, bot, notes)
    except Exception:
        log.exception("notes: saving card %s failed", card.message_id)
        restore_draft(card.chat.id, card.message_id, draft)
        await callback.answer("Could not save — try again.", show_alert=True)
        return
    await callback.answer()


@router.callback_query(NotesCB.filter(F.action == "offer"))
async def offer_handler(
    callback: CallbackQuery, callback_data: NotesCB, notes: NotesRuntime | None
) -> None:
    message = _admin_message(callback)
    if notes is None:
        await callback.answer("Notes are unavailable right now.", show_alert=True)
        return
    item = await asyncio.to_thread(items.get_item, notes.db, callback_data.item_id)
    await callback.answer()
    if message is None or item is None or item.url is None:
        return
    await offer_link(message, item.url, callback.from_user.id)


@router.callback_query(NotesCB.filter(F.action == "restore"))
async def restore_handler(
    callback: CallbackQuery, callback_data: NotesCB, notes: NotesRuntime | None
) -> None:
    message = _admin_message(callback)
    if (
        message is None
        or notes is None
        or await asyncio.to_thread(items.get_item, notes.db, callback_data.item_id) is None
    ):
        await callback.answer()
        return
    item = await asyncio.to_thread(items.set_placement, notes.db, callback_data.item_id, "active")
    await callback.answer("Вернул")
    # A repeat tap: the card already shows this state.
    with contextlib.suppress(TelegramBadRequest):
        await message.edit_text(
            notes_ui.acknowledgement(item), reply_markup=notes_ui.item_keyboard(item)
        )
