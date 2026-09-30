"""Notes for the admin: 💾 on the card saves, then enriches in the background (ADR-015)."""

from __future__ import annotations

import asyncio
import contextlib
import io
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any

import aiohttp
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
from notes.enrich.providers import is_social_media, is_youtube
from notes.sweeper import run_sweeper
from shared.config import settings
from shared.obs import get_logger

from .. import notes_ui
from ..access import is_admin
from ..keyboards import JobCB
from ..notes_ui import NotesCB
from .documents import (
    Draft,
    body_of,
    draft_of,
    first_link,
    is_agent_document,
    offer_link,
    restore_draft,
    take_draft,
)

log = get_logger(__name__)

router = Router(name="notes")

PREVIEW_MAX_BYTES = 300_000


def is_direct_host(url: str) -> bool:
    """Instagram, YouTube and TikTok links are saved as they are: there is no article to scrape."""
    return is_youtube(url) or is_social_media(url)


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
    await _acknowledge(card, captured, bot, notes)


async def _acknowledge(
    card: Message, captured: list[tuple[Item, str | None]], bot: Bot, notes: NotesRuntime
) -> None:
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


def _is_direct_link(message: Message) -> bool:
    """The admin's message whose first link is Instagram, YouTube or TikTok: saved with no card."""
    user = message.from_user
    if user is None or not is_admin(user.id) or message.document is not None:
        return False
    if message.photo or message.video or body_of(message).startswith("/"):
        return False
    url = first_link(draft_of(message))
    return url is not None and is_direct_host(url)


@router.message(_is_direct_link)
async def direct_link_handler(message: Message, bot: Bot, notes: NotesRuntime | None) -> None:
    """Admin: an Instagram / YouTube / TikTok link goes straight to notes (ADR-0007)."""
    user = message.from_user
    draft = draft_of(message)
    url = first_link(draft)
    if user is None or url is None:
        return
    if notes is None:  # notes are down: keep the old path
        await offer_link(message, url, user.id, draft)
        return
    card = await message.answer("💾 Сохраняю…")
    try:
        await _save(card, draft, bot, notes)
    except Exception:
        log.exception("notes: direct save of %s failed", url)
        await card.edit_text("⚠️ Не удалось сохранить — пришли ещё раз.")


def _is_admin_file(message: Message) -> bool:
    """The admin's photo, video or document that is not an agent document (.pdf/.docx/.md/.txt)."""
    user = message.from_user
    if user is None or not is_admin(user.id):
        return False
    if message.photo or message.video:
        return True
    document = message.document
    return document is not None and not is_agent_document(document.file_name or "document")


def _file_facts(message: Message) -> tuple[str, str | None, str | None, int | None, Any]:
    """(file_id, file_name, mime, size, thumbnail PhotoSize-like or None) of the media in `message`."""
    if message.photo:
        photos = message.photo
        best = photos[-1]
        return (
            best.file_id,
            None,
            "image/jpeg",
            best.file_size,
            photos[-2] if len(photos) > 1 else best,
        )
    if message.video:
        video = message.video
        return video.file_id, video.file_name, video.mime_type, video.file_size, video.thumbnail
    document = message.document
    assert document is not None
    return (
        document.file_id,
        document.file_name,
        document.mime_type,
        document.file_size,
        document.thumbnail,
    )


async def _download_preview(bot: Bot, thumb: Any) -> tuple[bytes, str] | None:
    if thumb is None or (thumb.file_size or 0) > PREVIEW_MAX_BYTES:
        return None
    buffer = io.BytesIO()
    try:
        await bot.download(thumb, destination=buffer)
    except aiohttp.ClientError:  # aiohttp's error text embeds the download URL, which has the token
        log.warning("notes: preview download failed")
        return None
    return (buffer.getvalue(), "image/jpeg") if buffer.getvalue() else None


@router.message(_is_admin_file)
async def file_handler(message: Message, bot: Bot, notes: NotesRuntime | None) -> None:
    """Admin: a photo or non-text file is saved as a File Item, with its preview for the Mini App."""
    if notes is None:
        await message.answer("Notes are unavailable right now.")
        return
    file_id, file_name, mime, size, thumb = _file_facts(message)
    card = await message.answer("💾 Сохраняю…")
    try:
        preview = await _download_preview(bot, thumb)
        item = await asyncio.to_thread(
            items.capture_file,
            notes.db,
            file_id=file_id,
            file_name=file_name,
            file_mime=mime,
            file_size=size,
            annotation=body_of(message),
            preview=preview,
            chat_id=card.chat.id,
        )
        await _acknowledge(card, [(item, None)], bot, notes)
    except Exception:
        log.exception("notes: saving a file failed")
        await card.edit_text("⚠️ Не удалось сохранить — пришли ещё раз.")


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
