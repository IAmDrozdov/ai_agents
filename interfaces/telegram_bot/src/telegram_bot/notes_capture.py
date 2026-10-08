"""Notes intake for the bot: a Message or a 💾 Draft becomes a Capture, and the reaction says what happened."""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

import aiohttp
from aiogram import Bot
from aiogram.types import (
    Message,
    MessageOriginChannel,
    MessageOriginChat,
    MessageOriginHiddenUser,
    MessageOriginUser,
)

from notes.capture import Acknowledgement, Attachment, Captured, Origin, Payload, Text, capture
from notes.domain.urls import extract_urls
from shared.obs import get_logger

from . import notes_ui, routing
from .notes_runtime import NotesRuntime

log = get_logger(__name__)

PREVIEW_MAX_BYTES = 300_000


@dataclass(frozen=True)
class Draft(Text):
    """What 💾 saves: the admin's words of one message, held by its Estimate card until 💾, Cancel or Run."""

    sender: str | None = None
    message_id: int | None = None


def sender_of(message: Message) -> str | None:
    """Who a forwarded message came from: a person, a hidden user, a chat or a channel."""
    origin = message.forward_origin
    if isinstance(origin, MessageOriginUser):
        return origin.sender_user.full_name
    if isinstance(origin, MessageOriginHiddenUser):
        return origin.sender_user_name
    if isinstance(origin, MessageOriginChat):
        return origin.sender_chat.title or origin.sender_chat.full_name
    if isinstance(origin, MessageOriginChannel):
        return origin.chat.title or origin.chat.full_name
    return None


def draft_of(message: Message) -> Draft:
    """The admin's words and hidden links (read the way routing reads them), the Sender and the message."""
    incoming = routing.incoming_of(message)
    return Draft(
        words=incoming.text,
        links=incoming.linked,
        sender=sender_of(message),
        message_id=message.message_id,
    )


def links_of(draft: Draft) -> tuple[str, ...]:
    """Every URL in a Draft, plain and behind text, as notes counts them."""
    return extract_urls(draft.words, linked=draft.links).urls


async def _preview_of(bot: Bot, thumb: Any) -> tuple[bytes, str] | None:
    if thumb is None or (thumb.file_size or 0) > PREVIEW_MAX_BYTES:
        return None
    buffer = io.BytesIO()
    try:
        await bot.download(thumb, destination=buffer)
    except aiohttp.ClientError:  # aiohttp's error text embeds the download URL, which has the token
        log.warning("notes: preview download failed")
        return None
    return (buffer.getvalue(), "image/jpeg") if buffer.getvalue() else None


async def payload_of(bot: Bot, message: Message) -> Payload:
    """Text → Draft; photo/video/document → Attachment with its preview; voice/round video → Attachment(speech=True)."""
    if message.text is not None:
        return draft_of(message)
    caption = routing.incoming_of(message).text
    if message.voice is not None:
        voice = message.voice
        return Attachment(
            file_id=voice.file_id,
            mime=voice.mime_type or "audio/ogg",
            size=voice.file_size,
            caption=caption,
            duration_s=voice.duration,
            speech=True,
        )
    if message.video_note is not None:
        round_video = message.video_note
        return Attachment(
            file_id=round_video.file_id,
            mime="video/mp4",  # Telegram gives a video note no mime type; it is always mp4
            size=round_video.file_size,
            caption=caption,
            duration_s=round_video.duration,
            preview=await _preview_of(bot, round_video.thumbnail),
            speech=True,
        )
    if message.photo:
        photos = message.photo
        best = photos[-1]
        return Attachment(
            file_id=best.file_id,
            mime="image/jpeg",
            size=best.file_size,
            caption=caption,
            preview=await _preview_of(bot, photos[-2] if len(photos) > 1 else best),
        )
    if message.video:
        video = message.video
        return Attachment(
            file_id=video.file_id,
            mime=video.mime_type,
            size=video.file_size,
            caption=caption,
            file_name=video.file_name,
            preview=await _preview_of(bot, video.thumbnail),
        )
    document = message.document
    assert document is not None
    return Attachment(
        file_id=document.file_id,
        mime=document.mime_type,
        size=document.file_size,
        caption=caption,
        file_name=document.file_name,
        preview=await _preview_of(bot, document.thumbnail),
    )


async def capture_message(notes: NotesRuntime, bot: Bot, message: Message) -> None:
    """A direct Capture: ✍ at once, read the message, save, then what the Capture decided; 👎 if saving threw."""
    chat, mid = message.chat.id, message.message_id
    await notes_ui.react(bot, chat, mid, notes_ui.EMOJI["wait"])
    try:
        payload = await payload_of(bot, message)
        captured = await capture(
            notes.db, payload, Origin(chat, mid, sender_of(message)), classifier=notes.classifier
        )
    except Exception:
        log.exception("notes: capture of message %s failed", mid)
        await notes_ui.react(bot, chat, mid, notes_ui.EMOJI["look"])
        return
    await settle(notes, bot, chat, mid, captured, shown="wait")


async def settle(
    notes: NotesRuntime,
    bot: Bot,
    chat_id: int,
    message_id: int,
    captured: Captured,
    *,
    shown: Acknowledgement | None,
) -> None:
    """Show what the Capture decided: the Due line, the reaction (unless `shown` already is it), and Enrichment."""
    if captured.due is not None:
        await notes_ui.announce_due(bot, captured.item, captured.due, reply_to=message_id)
    if captured.acknowledgement != shown:
        await notes_ui.react(bot, chat_id, message_id, notes_ui.EMOJI[captured.acknowledgement])
    if captured.enrich:
        notes.enrich_later(bot, captured.item.id)
