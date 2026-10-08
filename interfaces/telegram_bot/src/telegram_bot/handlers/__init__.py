"""Router order matters for callbacks (documents claims MenuCB(page='job')) and for `/settings https://x`, `/help https://x`."""

from __future__ import annotations

from aiogram import Dispatcher

from .. import access
from . import admin, documents, notes, settings_menu, start, status


def setup_routers(dp: Dispatcher) -> None:
    dp.include_router(start.router)
    # Defense in depth for H1: the middleware's only unauthenticated path is /start
    # <payload>, but every other router gets its own access check too, so a regression
    # in that one exception can never carry a stranger into a different handler.
    for router in (
        admin.router,
        notes.router,
        documents.router,
        settings_menu.router,
        status.router,
    ):
        router.message.filter(access.allowed_user_filter)
        router.callback_query.filter(access.allowed_user_filter)
        dp.include_router(router)
