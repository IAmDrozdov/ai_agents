"""Throttled progress reporting: workflow progress calls → one edited status message."""

from __future__ import annotations

import asyncio

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

from shared.obs import get_logger

log = get_logger(__name__)

PHASE_LABELS = {
    "extracting": "📖 Extracting",
    "fetching": "📡 Fetching video",
    "transcribing": "🎧 Transcribing",
    "translating": "🌐 Translating",
    "synthesizing": "🎙 Synthesizing",
}


class ProgressReporter:
    """A `shared.job.Progress` that bridges the worker thread to a single Telegram
    message edited at most once per ``interval`` seconds."""

    def __init__(self, bot: Bot, chat_id: int, message_id: int, interval: float = 2.0) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._message_id = message_id
        self._interval = interval
        self._loop = asyncio.get_running_loop()
        self._phase: str | None = None
        self._done = 0
        self._total = 0
        self._dirty = asyncio.Event()
        self._last_text = ""

    # Called from the worker thread running the workflow.
    def phase(self, name: str, total: int) -> None:
        self._loop.call_soon_threadsafe(self._set, name, 0, total)

    def tick(self, done: int, total: int) -> None:
        self._loop.call_soon_threadsafe(self._set, None, done, total)

    def _set(self, phase: str | None, done: int, total: int) -> None:
        if phase is not None:
            self._phase = phase
        self._done = done
        self._total = total
        self._dirty.set()

    def _render(self) -> str:
        label = PHASE_LABELS.get(self._phase or "", "⏳ Working")
        if self._total > 0:
            return f"{label}… {self._done}/{self._total}"
        return f"{label}…"

    async def run(self) -> None:
        while True:
            await self._dirty.wait()
            self._dirty.clear()
            text = self._render()
            if text != self._last_text:
                try:
                    await self._bot.edit_message_text(
                        text, chat_id=self._chat_id, message_id=self._message_id
                    )
                    self._last_text = text
                except TelegramRetryAfter as exc:
                    await asyncio.sleep(exc.retry_after)
                    self._dirty.set()
                except TelegramBadRequest:
                    pass  # "message is not modified" and similar — ignore
            await asyncio.sleep(self._interval)
