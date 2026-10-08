"""FIFO job queue and the single worker task (= the one-job-at-a-time lock)."""

from __future__ import annotations

import asyncio
import collections
import html
import time
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile
from pydantic import BaseModel

from shared.audio import OggOpusError, concat_ogg_opus
from shared.config import settings
from shared.failures import Failure, diagnose, from_message
from shared.job import AudioDeliverable, FileDeliverable, Preview, Result
from shared.obs import get_logger

from . import db, eta
from .catalog import TG_UPLOAD_LIMIT
from .progress import ProgressReporter
from .registry import BY_ID
from .user_config import config_snapshot

log = get_logger(__name__)

# Keep each audio message safely under TG_UPLOAD_LIMIT (Telegram's cap is on raw
# file bytes; leave headroom for container/upload overhead).
PART_LIMIT = 48 * 1024 * 1024

# The daily cost cap bounds dollars, not job count — without this a user could still
# monopolise the single FIFO worker with a large number of near-free jobs.
MAX_QUEUED_JOBS_PER_USER = 5


def _pack_parts(parts: list[bytes], limit: int) -> list[tuple[bytes, float]] | None:
    """Group ordered Opus blobs into batches whose joined size stays <= limit.

    Each batch is stitched into a single logical Ogg stream (not a chained file), so
    every part carries its own honest duration. Returns `(bytes, duration_s)` per
    batch, or None if a single blob already exceeds the limit or the blobs are not
    well-formed Ogg-Opus.
    """
    batches: list[list[bytes]] = []
    cur: list[bytes] = []
    cur_size = 0
    for part in parts:
        if len(part) > limit:
            return None
        if cur and cur_size + len(part) > limit:
            batches.append(cur)
            cur, cur_size = [], 0
        cur.append(part)
        cur_size += len(part)
    if cur:
        batches.append(cur)
    try:
        return [concat_ogg_opus(batch) for batch in batches]
    except OggOpusError:
        log.warning("could not stitch opus parts for splitting")
        return None


@dataclass
class Job:
    user_id: int
    chat_id: int
    username: str | None
    workflow_id: str
    title: str
    source_size_bytes: int
    config: BaseModel
    preview: Preview
    status_message_id: int
    # The estimate the user accepted; counts toward their daily cap while queued or running.
    estimated_cost_usd: float
    cancelled: bool = field(default=False)


class JobQueue:
    """FIFO with position queries and cancellation. Single consumer."""

    def __init__(self) -> None:
        self._items: collections.deque[Job] = collections.deque()
        self._not_empty = asyncio.Event()
        self.current: Job | None = None

    def put(self, job: Job) -> int:
        """Enqueue; returns 1-based position counting the running job."""
        self._items.append(job)
        self._not_empty.set()
        return len(self._items) + (1 if self.current else 0)

    async def get(self) -> Job:
        while not self._items:
            self._not_empty.clear()
            await self._not_empty.wait()
        return self._items.popleft()

    def cancel_for_user(self, user_id: int) -> int:
        count = 0
        for job in self._items:
            if job.user_id == user_id and not job.cancelled:
                job.cancelled = True
                count += 1
        return count

    def snapshot(self) -> list[Job]:
        return [job for job in self._items if not job.cancelled]

    def count_for_user(self, user_id: int) -> int:
        """Queued + running job count for one user, for the per-user queue cap."""
        count = sum(1 for job in self._items if job.user_id == user_id and not job.cancelled)
        if self.current is not None and self.current.user_id == user_id:
            count += 1
        return count

    def reserved_cost(self, user_id: int) -> float:
        """Estimated spend a user has queued or running — not yet in the usage log."""
        total = sum(
            job.estimated_cost_usd
            for job in self._items
            if job.user_id == user_id and not job.cancelled
        )
        if self.current is not None and self.current.user_id == user_id:
            total += self.current.estimated_cost_usd
        return total


def _fmt_cost(value: float) -> str:
    return f"${value:.4f}"


def _run_workflow(job: Job, reporter: ProgressReporter) -> Result:
    return BY_ID[job.workflow_id].workflow.run(settings, job.config, job.preview, reporter)


async def _send_audio_result(
    bot: Bot,
    chat_id: int,
    data: bytes,
    stem: str,
    caption: str,
    duration: int | None,
    title: str | None = None,
) -> None:
    """Send speech as a voice message; fall back to an audio file (README "Audio delivery")."""
    if duration:
        try:
            await bot.send_voice(
                chat_id,
                BufferedInputFile(data, filename=f"{stem}.ogg"),
                caption=caption,
                duration=duration,
            )
            return
        except TelegramBadRequest as exc:
            # Chiefly VOICE_MESSAGES_FORBIDDEN: Premium users can refuse voice notes.
            log.warning("send_voice rejected (%s) — falling back to send_audio", exc)
    await bot.send_audio(
        chat_id,
        BufferedInputFile(data, filename=f"{stem}.ogg"),
        caption=caption,
        title=title or stem,
        duration=duration,
    )


def _caption(icon: str, title: str, result: Result) -> str:
    lines = [f"{icon} {html.escape(title)}"]
    if result.facts:
        lines.append(" · ".join(f"{f.label}: {html.escape(f.value)}" for f in result.facts))
    lines.append(f"Cost: {_fmt_cost(result.cost.total_usd)}")
    return "\n".join(lines)


async def _deliver(bot: Bot, job: Job, result: Result) -> tuple[int, str | None]:
    """Send the deliverable. Returns (output_size, delivery_error)."""
    deliverable = result.deliverable
    if deliverable is None:
        return 0, "the workflow produced nothing to send"

    if isinstance(deliverable, FileDeliverable):
        output = deliverable.data
        if len(output) > TG_UPLOAD_LIMIT:
            return len(output), (
                f"Result is {len(output) / 1024 / 1024:.1f} MB — over Telegram's 50 MB bot limit."
            )
        await bot.send_document(
            job.chat_id,
            BufferedInputFile(output, filename=deliverable.filename),
            caption=_caption("📄", job.title, result),
        )
        return len(output), None

    audio: AudioDeliverable = deliverable
    stem = PurePosixPath(audio.filename).stem
    caption = _caption("🔊", job.title, result)
    duration = round(audio.duration_s) or None

    # Fits in one message — one voice note for the whole document.
    if len(audio.data) <= TG_UPLOAD_LIMIT:
        await _send_audio_result(bot, job.chat_id, audio.data, stem, caption, duration)
        return len(audio.data), None

    # Over the limit — split at chunk boundaries into multiple voice messages.
    batches = _pack_parts(audio.parts, PART_LIMIT) if audio.parts else None
    if not batches:
        return len(audio.data), (
            f"Audio is {len(audio.data) / 1024 / 1024:.1f} MB — over Telegram's 50 MB bot limit "
            "and could not be split. Try a smaller document."
        )
    total_parts = len(batches)
    for i, (batch, batch_duration) in enumerate(batches, start=1):
        part_name = f"{stem}.part{i}"
        part_caption = (
            caption if i == 1 else f"🔊 {html.escape(part_name)} (Part {i}/{total_parts})"
        )
        await _send_audio_result(
            bot,
            job.chat_id,
            batch,
            part_name,
            part_caption,
            round(batch_duration) or None,
            title=f"{stem} ({i}/{total_parts})",
        )
    return len(audio.data), None


_SCOPE_BADGE: dict[str, str] = {
    "provider": "🟡 Their side (OpenAI)",
    "config": "🔴 Our side — configuration",
    "internal": "🔴 Our side — bug",
    "input": "🟠 This document",
}
_VERDICT_ICON: dict[str, str] = {
    "provider": "⏳",
    "config": "🔧",
    "internal": "🔧",
    "input": "📄",
}


def _format_failure(failure: Failure) -> str:
    """Render a verdict, leading with the only thing worth knowing: wait, or fix?"""
    lines = [
        f"❌ <b>Failed</b> — {html.escape(failure.headline)}",
        "",
        _SCOPE_BADGE[failure.scope],
        html.escape(failure.detail),
    ]
    if failure.health and (checked := failure.health.summary()):
        lines.append(f"<i>Checked: {html.escape(checked)}</i>")
    lines += [
        "",
        f"{_VERDICT_ICON[failure.scope]} <b>{html.escape(failure.verdict)}</b>",
        html.escape(failure.action),
    ]
    return "\n".join(lines)


async def _edit_status(bot: Bot, job: Job, text: str) -> None:
    try:
        await bot.edit_message_text(text, chat_id=job.chat_id, message_id=job.status_message_id)
    except Exception:
        log.exception("failed to edit status message")


def _stats_json(result: Result) -> dict[str, Any]:
    return {
        "cost": asdict(result.cost),
        "facts": [asdict(fact) for fact in result.facts],
    }


async def _process(bot: Bot, job: Job) -> None:
    reporter = ProgressReporter(bot, job.chat_id, job.status_message_id)
    ticker = asyncio.create_task(reporter.run())
    started = time.monotonic()
    job_row_id = await asyncio.to_thread(
        db.insert_job,
        job.user_id,
        job.username,
        job.workflow_id,
        job.title,
        job.source_size_bytes,
        config_snapshot(job.config),
        job.estimated_cost_usd,
    )
    try:
        result = await asyncio.to_thread(_run_workflow, job, reporter)
        duration_s = time.monotonic() - started
        ticker.cancel()

        if result.error:
            await _edit_status(bot, job, _format_failure(from_message(result.error)))
            await asyncio.to_thread(
                db.finish_job,
                job_row_id,
                "error",
                error=result.error,
                cost_usd=result.cost.total_usd,
                duration_s=duration_s,
            )
            eta.note_job_finished()
            return

        output_size, delivery_error = await _deliver(bot, job, result)
        if delivery_error:
            await _edit_status(bot, job, f"⚠️ Done, but not delivered: {delivery_error}")
        else:
            await _edit_status(
                bot,
                job,
                f"✅ Done in {duration_s:.0f}s · cost {_fmt_cost(result.cost.total_usd)}",
            )
        await asyncio.to_thread(
            db.finish_job,
            job_row_id,
            "ok",
            error=delivery_error,
            cost_usd=result.cost.total_usd,
            char_count=job.preview.char_count,
            stats=_stats_json(result),
            duration_s=duration_s,
            output_size_bytes=output_size,
        )
        eta.note_job_finished()
    except Exception as exc:
        log.exception("job failed")
        ticker.cancel()
        # Blocking: a provider verdict is confirmed with a live probe, not assumed.
        failure = await asyncio.to_thread(diagnose, exc, settings)
        await _edit_status(bot, job, _format_failure(failure))
        await asyncio.to_thread(
            db.finish_job,
            job_row_id,
            "error",
            error=f"[{failure.scope}] {failure.headline}: {failure.detail}",
            # An unhandled exception may have already billed some chunks (M4); the
            # approved estimate is the safe upper bound to count toward the daily cap.
            cost_usd=job.estimated_cost_usd,
            duration_s=time.monotonic() - started,
        )
        eta.note_job_finished()
    finally:
        if not ticker.done():
            ticker.cancel()


async def worker_loop(bot: Bot, queue: JobQueue) -> None:
    log.info("worker loop started")
    while True:
        job = await queue.get()
        if job.cancelled:
            await _edit_status(bot, job, "✖️ Cancelled")
            continue
        queue.current = job
        try:
            await _process(bot, job)
        except Exception:
            log.exception("worker iteration failed")
        finally:
            queue.current = None
