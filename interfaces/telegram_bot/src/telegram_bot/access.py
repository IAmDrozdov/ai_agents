"""Access control: single admin, one-time invite links, whitelist middleware."""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import CallbackQuery, Message, TelegramObject, Update, User

from shared.config import settings
from shared.obs import get_logger

from . import db

log = get_logger(__name__)

REJECTION_TEXT = "This is a private bot. Ask the owner for an invite link."

# In-memory mirror of the users table to keep the middleware off the DB on the
# hot path; misses fall back to sqlite and populate the cache.
_whitelist_cache: set[int] = set()

# A stranger who keeps messaging should not hit sqlite, or get a reply, on every
# single message — both are a cheap flood-control target.
_NEGATIVE_TTL_S = 300
_REPLY_INTERVAL_S = 300
# Keyed by any stranger's id, so they need a ceiling of their own.
_FLOOD_CACHE_MAX = 10_000
_negative_cache: dict[int, float] = {}
_last_reply: dict[int, float] = {}


def _remember(cache: dict[int, float], user_id: int, now: float) -> None:
    """Timestamp a user, dropping stale entries first so a flood cannot grow memory."""
    if len(cache) >= _FLOOD_CACHE_MAX:
        cutoff = now - max(_NEGATIVE_TTL_S, _REPLY_INTERVAL_S)
        for uid, seen in list(cache.items()):
            if seen < cutoff:
                del cache[uid]
        if len(cache) >= _FLOOD_CACHE_MAX:
            cache.clear()
    cache[user_id] = now


def is_admin(user_id: int) -> bool:
    return settings.admin_telegram_id is not None and user_id == settings.admin_telegram_id


def cache_whitelisted(user_id: int) -> None:
    _whitelist_cache.add(user_id)


def forget(user_id: int) -> None:
    _whitelist_cache.discard(user_id)


async def is_allowed(user_id: int) -> bool:
    if is_admin(user_id) or user_id in _whitelist_cache:
        return True
    now = time.monotonic()
    negative_at = _negative_cache.get(user_id)
    if negative_at is not None and now - negative_at < _NEGATIVE_TTL_S:
        return False
    if await asyncio.to_thread(db.is_whitelisted, user_id):
        _whitelist_cache.add(user_id)
        _negative_cache.pop(user_id, None)
        return True
    _remember(_negative_cache, user_id, now)
    return False


async def allowed_user_filter(event: Message | CallbackQuery) -> bool:
    """Defense in depth: attached to every router but `start` (see `handlers/__init__.py`).

    The middleware's only unauthenticated path is `/start <payload>`; this filter makes
    sure that path can never accidentally carry a user into a different router too.
    """
    user = event.from_user
    return user is not None and await is_allowed(user.id)


def mint_invite(created_by: int) -> str:
    token = secrets.token_urlsafe(16)
    db.create_invite(token, created_by)
    return token


def _is_start_with_payload(message: Message) -> bool:
    text = message.text or ""
    parts = text.split(maxsplit=1)
    # Exact match only: a bot-mentioned command like "/start@other_bot" is not this
    # bot's /start (aiogram's own CommandStart rejects it too — see H1 in the review),
    # so it must not be treated as the one unauthenticated path through the middleware.
    return len(parts) == 2 and parts[0] == "/start"


class AccessMiddleware(BaseMiddleware):
    """Outer middleware on Update: drop everything from unknown users.

    The only unauthenticated path allowed through is ``/start <token>`` so the
    start handler can redeem an invite.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Update):
            return await handler(event, data)

        message: Message | None = event.message
        callback: CallbackQuery | None = event.callback_query
        user: User | None = None
        if message and message.from_user:
            user = message.from_user
        elif callback and callback.from_user:
            user = callback.from_user

        if user is None:
            return None  # channel posts, polls, etc. — not for this bot

        chat = None
        if message:
            chat = message.chat
        elif callback and callback.message:
            chat = callback.message.chat
        if chat is not None and chat.type != ChatType.PRIVATE:
            # In a group, other members could run or read a whitelisted user's job.
            if callback:
                await callback.answer("This bot works in private chats only.", show_alert=True)
            return None

        if await is_allowed(user.id):
            return await handler(event, data)

        if message and _is_start_with_payload(message):
            return await handler(event, data)

        log.info("access denied for telegram user %s", user.id)
        now = time.monotonic()
        if now - _last_reply.get(user.id, 0.0) < _REPLY_INTERVAL_S:
            return None
        _remember(_last_reply, user.id, now)
        try:
            if callback:
                await callback.answer(REJECTION_TEXT, show_alert=True)
            elif message:
                await message.answer(REJECTION_TEXT)
        except TelegramRetryAfter:
            pass
        return None
