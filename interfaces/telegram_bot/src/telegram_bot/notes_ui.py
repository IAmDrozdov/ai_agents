"""Notes presentation: Acknowledgement text and keyboard, in Russian, HTML-escaped (ADR-015)."""

from __future__ import annotations

from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyParameters, WebAppInfo

from notes.domain.items import Capture, Item
from notes.domain.sections import Section
from notes.enrich.providers import is_social_media
from shared.config import settings
from shared.obs import get_logger

log = get_logger(__name__)

HELP = (
    "\n\n📌 <b>Notes</b> (admin only): any text or link you send gets a card — "
    "💾 save to notes, one of the agents above, or cancel. Voice and round video messages "
    "are saved and transcribed straight away. Saved items are filed into "
    "sections; browse and sort them in the app (the 📒 button next to the message field)."
)
STATUS_LABELS = {"new": "новое", "started": "начато", "done": "готово"}
DUPLICATE_PREFIX = {
    "existing": "🔁 Уже сохранено",
    "restored": "♻️ Достал из корзины",
    "archived": "📦 Лежит в архиве",
}
TITLE_LIMIT = 300
OFFER_LABEL = "🤖 Агенты"
RETURN_LABEL = "↩️ Вернуть"
OPEN_LABEL = "✏️ Открыть"
SHOW_TEXT = "↩️ Вот оно"


class NotesCB(CallbackData, prefix="n"):
    """Notes actions on an Item: action is 'offer' (price card) or 'restore' (back to active)."""

    action: str
    item_id: int


def sections_line(sections: tuple[Section, ...]) -> str:
    return " · ".join(f"{s.emoji} {escape(s.name)}" for s in sections)


def title_of(item: Item) -> str:
    fallback = "🎤 Голосовое" if item.kind == "voice" else "Файл"
    text = item.title or item.url or item.file_name or item.text or fallback
    return escape(text if len(text) <= TITLE_LIMIT else text[: TITLE_LIMIT - 1] + "…")


def acknowledgement(item: Item) -> str:
    if item.enrichment_status == "pending":
        tail = {"link": "⏳ Разбираю ссылку…", "voice": "⏳ Расшифровываю…"}.get(
            item.kind, "⏳ Разбираю…"
        )
        return f"💾 Сохранено · {sections_line(item.sections)}\n{tail}"
    lines = [sections_line(item.sections), f"<b>{title_of(item)}</b>"]
    if item.gist:
        lines.append(escape(item.gist))
    origin = " · ".join(escape(part) for part in (item.source, item.author) if part)
    if item.sender:
        origin = " · ".join(part for part in (origin, f"↪️ {escape(item.sender)}") if part)
    if origin:
        lines.append(f"<i>{origin}</i>")
    if item.enrichment_status == "failed":
        lines.append("⚠️ Не смог разобрать — попробую ещё раз позже")
    return "\n".join(lines)


def duplicate(capture: Capture) -> str:
    item = capture.item
    return (
        f"{DUPLICATE_PREFIX[capture.outcome]}: <b>{title_of(item)}</b>\n"
        f"{sections_line(item.sections)} · {STATUS_LABELS[item.status]}"
    )


def item_keyboard(item: Item) -> InlineKeyboardMarkup | None:
    row: list[InlineKeyboardButton] = []
    # Telegram rejects a web_app button that is not https, and a rejected keyboard would fail the save.
    # A query string, never a #fragment: Telegram puts its launch data in the fragment (ADR-016).
    base = settings.bot_miniapp_url.strip().rstrip("/")
    if base.startswith("https://"):
        url = f"{base}/?item={item.id}"
        row.append(InlineKeyboardButton(text=OPEN_LABEL, web_app=WebAppInfo(url=url)))
    if item.kind == "link" and item.url and not is_social_media(item.url):
        row.append(
            InlineKeyboardButton(
                text=OFFER_LABEL, callback_data=NotesCB(action="offer", item_id=item.id).pack()
            )
        )
    rows = [row] if row else []
    if item.placement == "archived":
        restore = InlineKeyboardButton(
            text=RETURN_LABEL, callback_data=NotesCB(action="restore", item_id=item.id).pack()
        )
        rows.append([restore])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


async def edit_acknowledgement(bot: Bot, item: Item) -> None:
    if item.tg_chat_id is None or item.tg_ack_message_id is None:
        return
    try:
        await bot.edit_message_text(
            text=acknowledgement(item),
            chat_id=item.tg_chat_id,
            message_id=item.tg_ack_message_id,
            reply_markup=item_keyboard(item),
        )
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            log.warning("item %s: could not edit its acknowledgement: %s", item.id, exc)
    except TelegramAPIError as exc:
        log.warning("item %s: could not edit its acknowledgement: %s", item.id, exc)


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
