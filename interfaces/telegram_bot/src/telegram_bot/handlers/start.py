"""/start (with invite deep link) and /help."""

from __future__ import annotations

import asyncio

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message

from shared.obs import get_logger

from .. import access, db, notes_ui

log = get_logger(__name__)

router = Router(name="start")

HELP_TEXT = (
    "🤖 <b>Maxi bot</b>\n\n"
    "Send me a document (<code>.pdf</code>, <code>.docx</code>, <code>.md</code>, "
    "<code>.txt</code>, up to 20 MB) <b>or paste a link</b> (e.g. a blog "
    "article — I extract the readable text) and pick an agent:\n"
    "• 📄 <b>Document Translator</b> — chapter-by-chapter translation to Markdown\n"
    "• 🔊 <b>Document → Audio</b> — text-to-speech, optionally translated first\n"
    "• 🎬 <b>YouTube → dubbed audio</b> — paste a YouTube link, get a voice-over in your target language\n\n"
    "Commands:\n"
    "/settings — languages, models, voice (remembered per user)\n"
    "/status — current and queued jobs\n"
    "/cancel — cancel your queued jobs\n"
    "/help — this message\n\n"
    "One job runs at a time; extra jobs wait in a queue."
)


def _help_for(user_id: int) -> str:
    return HELP_TEXT + notes_ui.HELP if access.is_admin(user_id) else HELP_TEXT


@router.message(CommandStart())
async def start_handler(message: Message, command: CommandObject) -> None:
    user = message.from_user
    if user is None:
        return

    if await access.is_allowed(user.id):
        await asyncio.to_thread(db.upsert_user, user.id, user.username, user.first_name)
        await message.answer(_help_for(user.id))
        return

    token = (command.args or "").strip()
    if token and await asyncio.to_thread(
        db.redeem_invite, token, user.id, user.username, user.first_name
    ):
        access.cache_whitelisted(user.id)
        log.info("invite redeemed by telegram user %s", user.id)
        await message.answer("🎉 Welcome! Your invite has been accepted.\n\n" + HELP_TEXT)
        return

    await message.answer(access.REJECTION_TEXT)


@router.message(Command("help"))
async def help_handler(message: Message) -> None:
    user = message.from_user
    await message.answer(_help_for(user.id) if user else HELP_TEXT)
