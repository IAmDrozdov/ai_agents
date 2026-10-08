"""Document or link → priced estimate card → one-tap run."""

from __future__ import annotations

import asyncio
import io

import aiohttp
from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message

from shared.config import settings
from shared.job import DocumentSource, Estimate
from shared.obs import get_logger

from .. import db, eta, routing
from ..access import is_admin
from ..cards import CardBook, fmt_cost
from ..catalog import (
    DAILY_COST_WINDOW_HOURS,
    DAILY_USER_COST_LIMIT_USD,
    MAX_JOB_COST_USD,
    TG_DOWNLOAD_LIMIT,
)
from ..keyboards import JobCB, MenuCB, editable, root_menu
from ..notes_capture import draft_of
from ..registry import by_id
from ..worker import MAX_QUEUED_JOBS_PER_USER, Job, JobQueue

log = get_logger(__name__)

router = Router(name="documents")

EXPIRED = "This job has expired — send the document again."
UNAVAILABLE = "That action is unavailable for this document."


async def _spend_block_reason(user_id: int, estimate: Estimate, reserved: float) -> str | None:
    """Why this job must not run, or None; `reserved` is the user's queued + running estimate."""
    cost = estimate.cost.total_usd
    if cost > MAX_JOB_COST_USD:
        return (
            f"This job is estimated at {fmt_cost(cost)}, over the "
            f"{fmt_cost(MAX_JOB_COST_USD)} per-job limit. Split the document and send it "
            "in parts."
        )
    if is_admin(user_id):
        return None
    spent = await asyncio.to_thread(db.user_cost_since, user_id, DAILY_COST_WINDOW_HOURS)
    if spent + reserved + cost > DAILY_USER_COST_LIMIT_USD:
        queued = f" plus {fmt_cost(reserved)} queued" if reserved else ""
        return (
            f"You have spent {fmt_cost(spent)} in the last {DAILY_COST_WINDOW_HOURS}h{queued}, "
            f"and this job adds {fmt_cost(cost)}, over the {fmt_cost(DAILY_USER_COST_LIMIT_USD)} "
            "daily limit. Try again later or ask the owner."
        )
    return None


@router.message(routing.takes("document_card", "unsupported_document"))
async def document_handler(message: Message, bot: Bot, path: routing.Path, cards: CardBook) -> None:
    document = message.document
    user = message.from_user
    if document is None or user is None:
        return

    filename = document.file_name or "document"
    if path.kind == "unsupported_document":
        await message.answer(
            "Unsupported file type. Send a .pdf, .docx, .md, .markdown or .txt document."
        )
        return
    if document.file_size and document.file_size > TG_DOWNLOAD_LIMIT:
        await message.answer(
            "Telegram bots can only download files up to 20 MB. Please send a smaller document."
        )
        return

    buffer = io.BytesIO()
    try:
        await bot.download(document, destination=buffer)
    except aiohttp.ClientError:
        # aiohttp's own error text embeds the file-download URL, which carries the bot
        # token — caught here instead of letting it reach aiogram's default exception
        # logging (see the security review, L4).
        log.warning("document download failed for telegram user %s", user.id)
        await message.answer("❌ Couldn't download that file from Telegram. Please try again.")
        return
    file_bytes = buffer.getvalue()
    if not file_bytes:
        await message.answer("The file appears to be empty.")
        return

    await cards.offer_source(message, DocumentSource(file_bytes, filename), user.id)


@router.message(routing.takes("link_card"))
async def link_handler(message: Message, path: routing.Path, cards: CardBook) -> None:
    """Anyone's link → card; the admin's single website link also offers 💾 (ADR-015 §4)."""
    user = message.from_user
    if user is None or path.url is None:
        return
    await cards.offer_link(message, path.url, user.id, draft_of(message) if path.savable else None)


@router.callback_query(JobCB.filter(F.action == "run"))
async def run_job_handler(
    callback: CallbackQuery, callback_data: JobCB, queue: JobQueue, cards: CardBook
) -> None:
    message = editable(callback)
    workflow_id = callback_data.workflow
    entry = by_id(workflow_id)
    if message is None or entry is None:
        await callback.answer(EXPIRED, show_alert=True)
        return

    user = callback.from_user
    async with cards.run_attempt(message.chat.id, message.message_id, user.id) as attempt:
        item = attempt.pending
        if item is None:
            await callback.answer(EXPIRED, show_alert=True)
            return
        offered = item.estimates.get(workflow_id)
        if offered is None or offered.error:
            await callback.answer(UNAVAILABLE, show_alert=True)
            return
        if queue.count_for_user(user.id) >= MAX_QUEUED_JOBS_PER_USER:
            await callback.answer(
                f"You already have {MAX_QUEUED_JOBS_PER_USER} jobs queued or running. "
                "Wait for one to finish, or /cancel some first.",
                show_alert=True,
            )
            return

        stored = await asyncio.to_thread(db.get_user_settings, user.id)
        config = entry.build_config(stored)
        preview = item.previews[workflow_id]
        # Re-price with the settings in force now: the card's estimate may predate a model change.
        estimate = await asyncio.to_thread(entry.workflow.estimate, settings, config, preview)
        if estimate.error:
            await callback.answer(UNAVAILABLE, show_alert=True)
            return
        if blocked := await _spend_block_reason(user.id, estimate, queue.reserved_cost(user.id)):
            await callback.answer(blocked, show_alert=True)
            return

        seconds = await asyncio.to_thread(
            eta.predict_seconds, workflow_id, config, preview.char_count
        )
        eta_label = eta.format_eta(seconds)
        job = Job(
            user_id=user.id,
            chat_id=message.chat.id,
            username=user.username,
            workflow_id=workflow_id,
            title=item.title,
            source_size_bytes=item.size_bytes,
            config=config,
            preview=preview,
            status_message_id=message.message_id,
            estimated_cost_usd=estimate.cost.total_usd,
        )
        position = queue.put(job)
        attempt.accept()
    await callback.answer()
    suffix = f" · {eta_label}" if eta_label else ""
    text = f"🚀 Starting…{suffix}" if position == 1 else f"⏳ Queued, position {position}{suffix}"
    await message.edit_text(text)


@router.callback_query(JobCB.filter(F.action == "settings"))
async def job_settings_handler(callback: CallbackQuery, cards: CardBook) -> None:
    message = editable(callback)
    if message is None or not cards.owns_job(message.chat.id, message.message_id):
        await callback.answer(EXPIRED, show_alert=True)
        return
    await callback.answer()
    await message.edit_text("⚙️ <b>Settings</b>", reply_markup=root_menu(with_job_back=True))


@router.callback_query(MenuCB.filter(F.page == "job"))
async def back_to_job_handler(callback: CallbackQuery, cards: CardBook) -> None:
    message = editable(callback)
    if message is None or not cards.owns_job(message.chat.id, message.message_id):
        await callback.answer(EXPIRED, show_alert=True)
        return
    await callback.answer("Re-estimating…")
    await cards.reprice(message, callback.from_user.id)


@router.callback_query(JobCB.filter(F.action == "cancel"))
async def cancel_pending_handler(callback: CallbackQuery, cards: CardBook) -> None:
    message = editable(callback)
    if message is not None:
        cards.cancel(message.chat.id, message.message_id)
        await message.edit_text("✖️ Cancelled")
    await callback.answer()
