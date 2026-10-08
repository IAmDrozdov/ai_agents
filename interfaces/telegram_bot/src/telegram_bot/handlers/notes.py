"""Notes for the admin: a Capture is saved, enriched in the background and acknowledged by a reaction."""

from __future__ import annotations

import asyncio
import contextlib

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from notes.capture import Origin
from notes.domain import items
from shared.obs import get_logger

from .. import notes_capture, notes_ui, routing
from ..access import is_admin
from ..cards import CardBook
from ..keyboards import JobCB
from ..notes_capture import Draft, draft_of, links_of
from ..notes_runtime import NotesRuntime
from ..notes_ui import NotesCB

log = get_logger(__name__)

router = Router(name="notes")


@router.message(routing.takes("capture_text"))
async def direct_text_handler(
    message: Message, bot: Bot, notes: NotesRuntime | None, path: routing.Path, cards: CardBook
) -> None:
    """Admin: text and social links go straight to notes as one Link or Note (ADR-0007, ADR-0009)."""
    user = message.from_user
    if user is None:
        return
    if notes is None:  # notes are down: a social link still gets the agents' card
        draft = draft_of(message)
        urls = links_of(draft)
        if len(urls) == 1:
            await cards.offer_link(message, urls[0], user.id, draft)
        else:
            await notes_ui.react(bot, message.chat.id, message.message_id, notes_ui.EMOJI["look"])
        return
    await notes_capture.capture_message(notes, bot, message)


@router.message(routing.takes("capture_file"))
async def file_handler(
    message: Message, bot: Bot, notes: NotesRuntime | None, path: routing.Path
) -> None:
    """Admin: a photo or non-text file is saved as a File Item, with its preview for the Mini App."""
    if notes is None:
        await notes_ui.react(bot, message.chat.id, message.message_id, notes_ui.EMOJI["look"])
        return
    await notes_capture.capture_message(notes, bot, message)


@router.message(routing.takes("capture_voice"))
async def voice_handler(
    message: Message, bot: Bot, notes: NotesRuntime | None, path: routing.Path
) -> None:
    """Admin: a voice or round video message becomes a Voice; Enrichment transcribes it."""
    if notes is None:
        await notes_ui.react(bot, message.chat.id, message.message_id, notes_ui.EMOJI["look"])
        return
    await notes_capture.capture_message(notes, bot, message)


def _admin_message(callback: CallbackQuery) -> Message | None:
    if not is_admin(callback.from_user.id):
        return None
    return callback.message if isinstance(callback.message, Message) else None


@router.callback_query(JobCB.filter(F.action == "save"))
async def save_handler(
    callback: CallbackQuery, bot: Bot, notes: NotesRuntime | None, cards: CardBook
) -> None:
    card = _admin_message(callback)
    if card is None or notes is None:
        await callback.answer("Notes are unavailable right now.", show_alert=True)
        return
    draft = cards.take_savable(card.chat.id, card.message_id)
    if not isinstance(draft, Draft):
        await callback.answer("This card has expired — send it again.", show_alert=True)
        return
    try:
        captured = await notes_capture.capture(
            notes.db,
            draft,
            Origin(card.chat.id, draft.message_id, draft.sender),
            classifier=notes.classifier,
        )
    except Exception:
        log.exception("notes: saving card %s failed", card.message_id)
        cards.restore_savable(card.chat.id, card.message_id, draft)
        await callback.answer("Could not save — try again.", show_alert=True)
        return
    try:
        await card.delete()
    except TelegramAPIError as exc:
        log.warning("notes: could not delete card %s: %s", card.message_id, exc)
    if draft.message_id is not None:
        await notes_capture.settle(notes, bot, card.chat.id, draft.message_id, captured, shown=None)
    elif captured.enrich:
        notes.enrich_later(bot, captured.item.id)
    await callback.answer()


@router.callback_query(NotesCB.filter(F.action == "offer"))
async def offer_handler(
    callback: CallbackQuery, callback_data: NotesCB, notes: NotesRuntime | None, cards: CardBook
) -> None:
    message = _admin_message(callback)
    if notes is None:
        await callback.answer("Notes are unavailable right now.", show_alert=True)
        return
    item = await asyncio.to_thread(items.get_item, notes.db, callback_data.item_id)
    await callback.answer()
    if message is None or item is None or item.url is None:
        return
    await cards.offer_link(message, item.url, callback.from_user.id)


@router.callback_query(NotesCB.filter(F.action == "done"))
async def reminder_done_handler(
    callback: CallbackQuery, callback_data: NotesCB, notes: NotesRuntime | None
) -> None:
    """A Reminder's ✅ Готово: the Item is done and the message says so (ADR-0011)."""
    message = _admin_message(callback)
    if message is None:
        await callback.answer()
        return
    if notes is None:
        await callback.answer("Notes are unavailable right now.", show_alert=True)
        return
    item = await asyncio.to_thread(items.edit_item, notes.db, callback_data.item_id, status="done")
    await callback.answer("Эта заметка уже удалена" if item is None else None)
    with contextlib.suppress(TelegramAPIError):
        if item is None:
            await message.edit_reply_markup(reply_markup=None)
        else:
            await message.edit_text(notes_ui.DONE_TEXT, reply_markup=None)


@router.callback_query(NotesCB.filter(F.action == "restore"))
async def stale_restore_handler(callback: CallbackQuery) -> None:
    """An old ↩️ button: it only removes itself (ADR-0010)."""
    message = _admin_message(callback)
    await callback.answer()
    if message is not None:  # the button goes; a repeat tap finds it gone already
        with contextlib.suppress(TelegramBadRequest):
            await message.edit_reply_markup(reply_markup=None)
