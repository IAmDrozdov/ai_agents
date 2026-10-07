"""Notes presentation: the Acknowledgement reaction, "show in chat" and Reminders, in Russian (ADR-015, 0009, 0011)."""

from __future__ import annotations

from datetime import UTC, datetime
from html import escape

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReactionTypeEmoji,
    ReplyParameters,
    WebAppInfo,
)

from notes.domain import items
from notes.domain.items import Item
from shared.config import settings
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
REMINDER_TEXT = "⏰ Напоминание"
DONE_TEXT = "✅ сделано"
RETRYABLE = (TelegramNetworkError, TelegramRetryAfter, TelegramServerError)


class NotesCB(CallbackData, prefix="n"):
    """Notes actions on an Item: 'offer' (price card), 'done' (a Reminder's ✅ Готово) or 'restore' (a dead button)."""

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


WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
MONTHS = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")


def format_due(due_at: str, zone: str) -> str:
    """A stored UTC Due in the Owner's zone, as «пт, 10 окт, 19:00»."""
    moment = datetime.strptime(due_at, items.TIMESTAMP).replace(tzinfo=UTC)
    local = moment.astimezone(items.zone(zone))
    return f"{WEEKDAYS[local.weekday()]}, {local.day} {MONTHS[local.month - 1]}, {local:%H:%M}"


def miniapp_link(item_id: int) -> str | None:
    """The Mini App opened on one Item, or None when no Mini App URL is configured."""
    base = settings.bot_miniapp_url.strip()
    return f"{base.rstrip('/')}/?item={item_id}" if base else None


def reminder_keyboard(item_id: int) -> InlineKeyboardMarkup:
    row = [
        InlineKeyboardButton(
            text="✅ Готово", callback_data=NotesCB(action="done", item_id=item_id).pack()
        )
    ]
    if link := miniapp_link(item_id):
        row.append(InlineKeyboardButton(text="📅 Перенести", web_app=WebAppInfo(url=link)))
    return InlineKeyboardMarkup(inline_keyboard=[row])


async def send_reminder(bot: Bot, item: Item) -> bool:
    """Reply to the Item's Capture message with ✅ / 📅; if it is gone, say what it was. False: retry later."""
    chat = item.tg_chat_id if item.tg_chat_id is not None else settings.admin_telegram_id
    if chat is None:
        return True
    markup = reminder_keyboard(item.id)
    try:
        if item.tg_message_id is not None:
            try:
                await bot.send_message(
                    chat,
                    REMINDER_TEXT,
                    reply_markup=markup,
                    reply_parameters=ReplyParameters(message_id=item.tg_message_id),
                )
                return True
            except TelegramBadRequest as exc:
                log.info("item %s: original message is gone: %s", item.id, exc)
        about = item.title or item.gist or title_of(item)
        await bot.send_message(
            chat, f"{REMINDER_TEXT}: <b>{escape(about)}</b>", reply_markup=markup
        )
    except RETRYABLE as exc:
        log.warning("item %s: could not send the reminder, will retry: %s", item.id, exc)
        return False
    except TelegramAPIError as exc:
        log.warning("item %s: could not send the reminder: %s", item.id, exc)
    return True


async def announce_due(bot: Bot, item: Item, zone: str, *, now: datetime | None = None) -> None:
    """One line naming the Due a Capture became a Reminder with; a Due already past says nothing."""
    chat = item.tg_chat_id
    if chat is None or item.due_at is None or item.due_at <= items.stamp(now):
        return
    link = miniapp_link(item.id)
    markup = (
        InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📅 Перенести", web_app=WebAppInfo(url=link))]
            ]
        )
        if link
        else None
    )
    text = f"⏰ {format_due(item.due_at, zone)}"
    reply = (
        ReplyParameters(message_id=item.tg_message_id, allow_sending_without_reply=True)
        if item.tg_message_id is not None
        else None
    )
    try:
        await bot.send_message(chat, text, reply_markup=markup, reply_parameters=reply)
    except TelegramAPIError as exc:
        log.warning("item %s: could not announce the Due: %s", item.id, exc)


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
