"""Entrypoint for the Telegram bot (long polling)."""

from __future__ import annotations

import asyncio
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand

from shared.config import settings
from shared.obs import get_logger

from . import db
from .access import AccessMiddleware
from .handlers import setup_routers
from .handlers.notes import build_runtime as build_notes_runtime
from .tracing import init_tracing
from .worker import JobQueue, worker_loop

log = get_logger(__name__)

COMMANDS = [
    BotCommand(command="help", description="What this bot does"),
    BotCommand(command="settings", description="Languages, models, voice"),
    BotCommand(command="status", description="Current and queued jobs"),
    BotCommand(command="cancel", description="Cancel your queued jobs"),
]


async def _run() -> None:
    token = settings.telegram_bot_token
    if token is None:
        log.error("TELEGRAM_BOT_TOKEN is not set — refusing to start")
        sys.exit(1)
    if settings.admin_telegram_id is None:
        log.warning("ADMIN_TELEGRAM_ID is not set — nobody can mint invites")

    db.init_db()
    if stale := db.reconcile_running_jobs():
        log.info("marked %d job(s) left running by a previous process as interrupted", stale)

    bot = Bot(token=token.get_secret_value(), default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    queue = JobQueue()
    dp["queue"] = queue
    # Notes is admin-only (ADR-015): if it cannot start, the bot runs without it and 💾 says so.
    try:
        notes = build_notes_runtime()
    except Exception:
        log.exception("notes disabled: could not start the notes store")
        notes = None
    dp["notes"] = notes
    dp.update.outer_middleware(AccessMiddleware())
    setup_routers(dp)

    # Held so the loop task is not garbage collected mid-flight.
    background: set[asyncio.Task[None]] = set()

    async def on_startup() -> None:
        me = await bot.me()
        log.info("polling as @%s (id=%s)", me.username, me.id)
        await bot.set_my_commands(COMMANDS)
        task = asyncio.create_task(worker_loop(bot, queue))
        background.add(task)
        task.add_done_callback(background.discard)
        if notes is not None:
            notes.start_sweeper(bot)

    dp.startup.register(on_startup)
    await dp.start_polling(bot)


def main() -> None:
    init_tracing(settings=settings)
    asyncio.run(_run())


if __name__ == "__main__":
    main()
