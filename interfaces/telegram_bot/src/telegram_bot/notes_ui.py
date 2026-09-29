"""Notes presentation: Acknowledgement text and keyboard, in Russian, HTML-escaped (ADR-015)."""

from __future__ import annotations

from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from notes.domain.items import Capture, Item
from notes.domain.sections import Section
from shared.obs import get_logger

log = get_logger(__name__)

HELP = (
    "\n\n📌 <b>Notes</b> (admin only): any text or link you send is saved first and filed "
    "into sections; a link's reply has a button to run the agents above on it. "
    "Browse and sort on the notes web UI (SSH tunnel, port 8082)."
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


class NotesCB(CallbackData, prefix="n"):
    """Notes actions on an Item: action is 'offer' (price card) or 'restore' (back to active)."""

    action: str
    item_id: int


def sections_line(sections: tuple[Section, ...]) -> str:
    return " · ".join(f"{s.emoji} {escape(s.name)}" for s in sections)


def title_of(item: Item) -> str:
    text = item.title or item.url or item.text
    return escape(text if len(text) <= TITLE_LIMIT else text[: TITLE_LIMIT - 1] + "…")


def acknowledgement(item: Item) -> str:
    if item.enrichment_status == "pending":
        tail = "⏳ Разбираю ссылку…" if item.kind == "link" else "⏳ Разбираю…"
        return f"💾 Сохранено · {sections_line(item.sections)}\n{tail}"
    lines = [sections_line(item.sections), f"<b>{title_of(item)}</b>"]
    if item.gist:
        lines.append(escape(item.gist))
    origin = " · ".join(escape(part) for part in (item.source, item.author) if part)
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
    if item.kind == "link" and item.url:
        row.append(
            InlineKeyboardButton(
                text=OFFER_LABEL, callback_data=NotesCB(action="offer", item_id=item.id).pack()
            )
        )
    if item.placement == "archived":
        row.append(
            InlineKeyboardButton(
                text=RETURN_LABEL, callback_data=NotesCB(action="restore", item_id=item.id).pack()
            )
        )
    return InlineKeyboardMarkup(inline_keyboard=[row]) if row else None


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
