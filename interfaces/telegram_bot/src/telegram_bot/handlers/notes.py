"""Notes Capture for the admin: every text or link is saved first, then enriched (ADR-015)."""

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

from .. import notes_ui
from ..access import is_admin
from ..notes_ui import NotesCB
from .documents import offer_link

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


def _body(message: Message) -> str:
    return (message.text or message.caption or "").strip()


def _hidden_links(message: Message) -> list[str]:
    entities = message.entities or message.caption_entities or []
    return [entity.url for entity in entities if entity.type == "text_link" and entity.url]


def is_capture(message: Message) -> bool:
    """Admin text (or a captioned non-document) that is not a command; files stay with documents."""
    user = message.from_user
    if user is None or not is_admin(user.id) or message.document is not None:
        return False
    body = _body(message)
    return bool(body) and not body.startswith("/")


async def _acknowledge(message: Message, item: Item, bot: Bot, notes: NotesRuntime) -> None:
    sent = await message.answer(
        notes_ui.acknowledgement(item), reply_markup=notes_ui.item_keyboard(item)
    )
    await asyncio.to_thread(
        items.set_ack_message, notes.db, item.id, chat_id=sent.chat.id, message_id=sent.message_id
    )
    notes.enrich_later(bot, item.id)


@router.message(is_capture)
async def capture_handler(message: Message, bot: Bot, notes: NotesRuntime) -> None:
    extracted = extract_urls(_body(message), linked=_hidden_links(message))
    if not extracted.urls:
        note = await asyncio.to_thread(
            items.capture_note, notes.db, extracted.annotation, chat_id=message.chat.id
        )
        await _acknowledge(message, note, bot, notes)
        return
    for url in extracted.urls:
        capture = await asyncio.to_thread(
            items.capture_link, notes.db, url, extracted.annotation, chat_id=message.chat.id
        )
        if capture.outcome == "new":
            await _acknowledge(message, capture.item, bot, notes)
        else:
            await message.answer(
                notes_ui.duplicate(capture), reply_markup=notes_ui.item_keyboard(capture.item)
            )


def _admin_message(callback: CallbackQuery) -> Message | None:
    if not is_admin(callback.from_user.id):
        return None
    return callback.message if isinstance(callback.message, Message) else None


@router.callback_query(NotesCB.filter(F.action == "offer"))
async def offer_handler(
    callback: CallbackQuery, callback_data: NotesCB, notes: NotesRuntime
) -> None:
    message = _admin_message(callback)
    item = await asyncio.to_thread(items.get_item, notes.db, callback_data.item_id)
    await callback.answer()
    if message is None or item is None or item.url is None:
        return
    await offer_link(message, item.url, callback.from_user.id)


@router.callback_query(NotesCB.filter(F.action == "restore"))
async def restore_handler(
    callback: CallbackQuery, callback_data: NotesCB, notes: NotesRuntime
) -> None:
    message = _admin_message(callback)
    if (
        message is None
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
