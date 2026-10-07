"""Notes presentation: the Acknowledgement reaction and "show in chat", in Russian (ADR-015, ADR-0009)."""

from __future__ import annotations

from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.types import ReactionTypeEmoji, ReplyParameters

from notes.domain.items import Item
from shared.obs import get_logger

log = get_logger(__name__)

HELP = (
    "\n\n📌 <b>Notes</b> (admin only): text, links, files, voice and round video messages are "
    "saved straight away. A single website link gets a card — 💾 save to notes, one of the agents "
    "above, or cancel; to run an agent on your own text, send it as a .txt file. The bot reacts "
    "to your message: ✍ working, 👌 saved, 👎 take a look. Saved items are filed into sections; "
    "browse and sort them in the app (the 📒 button next to the message field)."
)
WORKING, DONE, LOOK = "✍", "👌", "👎"
REACTIONS = {"pending": WORKING, "done": DONE, "failed": LOOK}
TITLE_LIMIT = 300
SHOW_TEXT = "↩️ Вот оно"


class NotesCB(CallbackData, prefix="n"):
    """Notes actions on an Item: action is 'offer' (price card) or 'restore' (an old, dead button)."""

    action: str
    item_id: int


def title_of(item: Item) -> str:
    fallback = "🎤 Голосовое" if item.kind == "voice" else "Файл"
    text = item.title or item.url or item.file_name or item.text or fallback
    return escape(text if len(text) <= TITLE_LIMIT else text[: TITLE_LIMIT - 1] + "…")


async def react(bot: Bot, chat_id: int, message_id: int, emoji: str) -> None:
    """Set the bot's one reaction on a message; a failure is logged, never raised."""
    try:
        await bot.set_message_reaction(
            chat_id=chat_id, message_id=message_id, reaction=[ReactionTypeEmoji(emoji=emoji)]
        )
    except TelegramAPIError as exc:
        log.warning("message %s: could not react %s: %s", message_id, emoji, exc)


async def acknowledge(bot: Bot, item: Item) -> None:
    """The reaction on the Item's Capture message that matches its Enrichment."""
    if item.tg_chat_id is None or item.tg_message_id is None:
        return
    await react(
        bot, item.tg_chat_id, item.tg_message_id, REACTIONS.get(item.enrichment_status, DONE)
    )


async def show_in_chat(bot: Bot, item: Item) -> None:
    """Reply to the Item's original message (the quote jumps to it); if it is gone, send it again."""
    if item.tg_chat_id is None:
        return
    if item.tg_message_id is not None:
        try:
            await bot.send_message(
                item.tg_chat_id,
                SHOW_TEXT,
                reply_parameters=ReplyParameters(message_id=item.tg_message_id),
            )
            return
        except TelegramBadRequest as exc:
            log.info("item %s: original message is gone: %s", item.id, exc)
        except TelegramAPIError as exc:
            log.warning("item %s: could not show it in the chat: %s", item.id, exc)
            return
    try:
        await _resend(bot, item)
    except TelegramAPIError as exc:
        log.warning("item %s: could not show it in the chat: %s", item.id, exc)


async def _resend(bot: Bot, item: Item) -> None:
    chat, file_id, mime = item.tg_chat_id, item.file_id, item.file_mime or ""
    assert chat is not None
    caption = f"{SHOW_TEXT}: <b>{title_of(item)}</b>"
    if file_id is None:
        await bot.send_message(chat, f"Оригинал удалён: <b>{title_of(item)}</b>")
    elif item.kind == "voice" and mime.startswith("video/"):
        await bot.send_video_note(chat, file_id)
    elif item.kind == "voice":
        await bot.send_voice(chat, file_id, caption=caption)
    elif item.file_name is None and mime.startswith("image/"):
        await bot.send_photo(chat, file_id, caption=caption)
    elif mime.startswith("video/"):
        try:
            await bot.send_video(chat, file_id, caption=caption)
        except TelegramBadRequest:  # a video sent as a document keeps a document file_id
            await bot.send_document(chat, file_id, caption=caption)
    else:
        await bot.send_document(chat, file_id, caption=caption)
