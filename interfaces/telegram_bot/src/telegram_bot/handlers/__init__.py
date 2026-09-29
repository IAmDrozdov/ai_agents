"""Router registration order matters: documents claims MenuCB(page='job'); notes precedes it."""

from __future__ import annotations

from aiogram import Dispatcher

from .. import access
from . import admin, documents, notes, settings_menu, start, status


def setup_routers(dp: Dispatcher, *, notes_enabled: bool = True) -> None:
    dp.include_router(start.router)
    # Defense in depth for H1: the middleware's only unauthenticated path is /start
    # <payload>, but every other router gets its own access check too, so a regression
    # in that one exception can never carry a stranger into a different handler.
    # notes (admin-only Capture) sits before documents so it wins the admin's links (ADR-015).
    routers = (admin.router, notes.router, documents.router, settings_menu.router, status.router)
    for router in routers:
        if router is notes.router and not notes_enabled:
            continue
        router.message.filter(access.allowed_user_filter)
        router.callback_query.filter(access.allowed_user_filter)
        dp.include_router(router)
