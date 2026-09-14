"""Admin-only commands: /invite (one-time links), /users and /revoke."""

from __future__ import annotations

import asyncio
import html

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from .. import access, db
from ..worker import JobQueue

router = Router(name="admin")


@router.message(Command("invite"))
async def invite_handler(message: Message, bot: Bot) -> None:
    user = message.from_user
    if user is None or not access.is_admin(user.id):
        await message.answer("Only the admin can mint invites.")
        return
    token = await asyncio.to_thread(access.mint_invite, user.id)
    me = await bot.me()
    link = f"https://t.me/{me.username}?start={token}"
    await message.answer(
        f"One-time invite link (single use, expires in {db.INVITE_TTL_HOURS}h):\n"
        f"<code>{html.escape(link)}</code>"
    )


@router.message(Command("users"))
async def users_handler(message: Message) -> None:
    user = message.from_user
    if user is None or not access.is_admin(user.id):
        await message.answer("Only the admin can list users.")
        return
    users = await asyncio.to_thread(db.list_users)
    if not users:
        await message.answer("No invited users yet.")
        return
    lines = [
        f"• <code>{u['telegram_id']}</code> "
        f"{html.escape(u['username'] or u['first_name'] or '')} — since {u['created_at']}"
        for u in users
    ]
    await message.answer("Invited users:\n" + "\n".join(lines))


@router.message(Command("revoke"))
async def revoke_handler(message: Message, command: CommandObject, queue: JobQueue) -> None:
    user = message.from_user
    if user is None or not access.is_admin(user.id):
        await message.answer("Only the admin can revoke users.")
        return
    raw = (command.args or "").strip()
    if not raw.isdigit():
        await message.answer("Usage: /revoke &lt;telegram_id&gt; — ids are listed by /users.")
        return
    target = int(raw)
    removed = await asyncio.to_thread(db.delete_user, target)
    access.forget(target)
    cancelled = queue.cancel_for_user(target)
    if not removed:
        await message.answer(f"No invited user with id <code>{target}</code>.")
        return
    await message.answer(
        f"Revoked <code>{target}</code>; {cancelled} queued job(s) cancelled. "
        "A job already running finishes, then nothing more is accepted."
    )
