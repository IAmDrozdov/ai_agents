"""/status and /cancel."""

from __future__ import annotations

import html

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from ..access import is_admin
from ..registry import label_for
from ..worker import Job, JobQueue

router = Router(name="status")


def _describe(job: Job, *, visible: bool) -> str:
    """Someone else's job is a queue position, not a filename."""
    label = label_for(job.workflow_id)
    if not visible:
        return f"{label} — <i>another user</i>"
    return f"{label} — <b>{html.escape(job.title)}</b>"


@router.message(Command("status"))
async def status_handler(message: Message, queue: JobQueue) -> None:
    user = message.from_user
    if user is None:
        return
    everything = is_admin(user.id)

    lines: list[str] = []
    if queue.current is not None:
        job = queue.current
        lines.append(f"▶️ Running: {_describe(job, visible=everything or job.user_id == user.id)}")
    for position, job in enumerate(queue.snapshot(), start=1):
        lines.append(f"{position}. {_describe(job, visible=everything or job.user_id == user.id)}")
    if not lines:
        await message.answer("Nothing running and the queue is empty.")
        return
    await message.answer("\n".join(lines))


@router.message(Command("cancel"))
async def cancel_handler(message: Message, queue: JobQueue) -> None:
    user = message.from_user
    if user is None:
        return
    count = queue.cancel_for_user(user.id)
    if count:
        await message.answer(f"✖️ Cancelled {count} queued job(s).")
    elif queue.current is not None and queue.current.user_id == user.id:
        await message.answer(
            "The running job cannot be interrupted; only queued jobs can be cancelled."
        )
    else:
        await message.answer("You have no queued jobs.")
