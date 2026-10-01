"""Document or link → priced estimate card → one-tap run."""

from __future__ import annotations

import asyncio
import html
import io
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from urllib.parse import urlparse

import aiohttp
from aiogram import Bot, F, Router
from aiogram.types import (
    CallbackQuery,
    Message,
    MessageOriginChannel,
    MessageOriginChat,
    MessageOriginHiddenUser,
    MessageOriginUser,
)

from notes.domain.urls import extract_urls
from notes.enrich.providers import is_social_media, is_youtube
from shared.config import settings
from shared.job import DocumentSource, Estimate, LinkSource, Preview, Source
from shared.obs import get_logger

from .. import db, eta, user_config
from ..access import is_admin
from ..catalog import (
    ALLOWED_EXTENSIONS,
    DAILY_COST_WINDOW_HOURS,
    DAILY_USER_COST_LIMIT_USD,
    MAX_JOB_COST_USD,
    SETTING_LABELS,
    TG_DOWNLOAD_LIMIT,
    option_label,
)
from ..keyboards import (
    ActionOption,
    JobCB,
    MenuCB,
    action_menu,
    draft_menu,
    root_menu,
    save_only_menu,
)
from ..registry import RegistryEntry, by_id, entries_for
from ..scrape import ScrapeError, filename_for, scrape_url
from ..worker import MAX_QUEUED_JOBS_PER_USER, Job, JobQueue

log = get_logger(__name__)

router = Router(name="documents")

# Intake (parsing a document, scraping a link, probing yt-dlp) is CPU/network work that
# used to share the asyncio default executor with every DB lookup and the worker itself
# — five slow previews could starve everything else (see the security review, M2). It
# now runs on its own small pool, one job in flight per user, with a hard timeout.
_INTAKE_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="intake")
_INTAKE_TIMEOUT_S = 120
_intake_locks: dict[int, asyncio.Lock] = {}
# Also used to close the daily-cap race on concurrent Run taps (L1): serializes one
# user's estimate -> spend-check -> enqueue critical section.
_run_locks: dict[int, asyncio.Lock] = {}


def _lock_for(registry: dict[int, asyncio.Lock], user_id: int) -> asyncio.Lock:
    lock = registry.get(user_id)
    if lock is None:
        lock = asyncio.Lock()
        registry[user_id] = lock
    return lock


async def _run_intake(user_id: int, func, *args):
    """Run blocking intake work off the loop, one at a time per user, with a timeout."""
    async with _lock_for(_intake_locks, user_id):
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(_INTAKE_EXECUTOR, func, *args),
            timeout=_INTAKE_TIMEOUT_S,
        )


_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}


def _is_youtube_url(url: str) -> bool:
    return urlparse(url).netloc.lower() in _YOUTUBE_HOSTS


@dataclass
class Pending:
    source: Source
    message_id: int | None = None
    previews: dict[str, Preview] = field(default_factory=dict)
    estimates: dict[str, Estimate] = field(default_factory=dict)
    created_at: float = field(default_factory=time.monotonic)
    # The admin's card also offers 💾 (ADR-015); the words to save live in `drafts`.
    savable: bool = False

    @property
    def size_bytes(self) -> int:
        return len(self.source.file_bytes) if isinstance(self.source, DocumentSource) else 0

    @property
    def title(self) -> str:
        if isinstance(self.source, DocumentSource):
            return self.source.filename
        for preview in self.previews.values():
            if preview.title:
                return preview.title
        return self.source.url


# One pending item per chat; a new one replaces the previous. Entries hold the
# whole file in RAM, so an abandoned card cannot be allowed to live forever.
PENDING_TTL_S = 30 * 60
PENDING_MAX_BYTES = 60 * 1024 * 1024

pending: dict[int, Pending] = {}


def _evict_pending(now: float | None = None) -> None:
    """Drop expired cards, then oldest-first until the cache fits in its budget."""
    now = time.monotonic() if now is None else now
    for chat_id, item in list(pending.items()):
        if now - item.created_at > PENDING_TTL_S:
            del pending[chat_id]
    total = sum(item.size_bytes for item in pending.values())
    if total <= PENDING_MAX_BYTES:
        return
    for chat_id, item in sorted(pending.items(), key=lambda kv: kv[1].created_at):
        if total <= PENDING_MAX_BYTES:
            break
        total -= item.size_bytes
        del pending[chat_id]


def _remember_pending(chat_id: int, item: Pending) -> None:
    # Touch on every (re)insert, including the put-back after a rejected run, so the
    # entry a user is actively working with is never the one evicted for age.
    item.created_at = time.monotonic()
    pending[chat_id] = item
    _evict_pending()


@dataclass(frozen=True)
class Draft:
    """What 💾 saves: the admin's own words, links hidden behind text, who forwarded it, from where."""

    text: str
    links: tuple[str, ...] = ()
    sender: str | None = None
    message_id: int | None = None


# (chat id, card message id) → Draft, until saved, cancelled, run or evicted.
DRAFTS_MAX = 50
drafts: dict[tuple[int, int], Draft] = {}
# chat id → the card message the in-flight intake may still edit. Cancel and 💾 close a
# card, so one that finishes pricing afterwards does not overwrite what the user chose; a
# newer message supersedes it (one pending job per chat).
_live: dict[int, int] = {}
_closed: dict[tuple[int, int], None] = {}


def _is_live(message: Message) -> bool:
    return _live.get(message.chat.id) == message.message_id


def _close(message: Message) -> None:
    if _is_live(message):
        del _live[message.chat.id]
    _closed[(message.chat.id, message.message_id)] = None
    while len(_closed) > DRAFTS_MAX:
        del _closed[next(iter(_closed))]


async def _still_live(status: Message) -> bool:
    """False when the card was closed or superseded; a superseded card says so."""
    if _is_live(status):
        return True
    if (status.chat.id, status.message_id) not in _closed:
        savable = (status.chat.id, status.message_id) in drafts
        await status.edit_text(
            "⏭ Replaced by your newer message.",
            reply_markup=save_only_menu() if savable else None,
        )
    return False


def _remember_draft(chat_id: int, message_id: int, draft: Draft) -> None:
    drafts[(chat_id, message_id)] = draft
    while len(drafts) > DRAFTS_MAX:
        del drafts[next(iter(drafts))]


def restore_draft(chat_id: int, message_id: int, draft: Draft) -> None:
    """Give a Draft back to its card after a failed save, so 💾 can be tried again."""
    _remember_draft(chat_id, message_id, draft)


def _pop_pending_for(message: Message) -> Pending | None:
    """The chat's pending job, only if it belongs to this card; an older card never takes it."""
    item = pending.get(message.chat.id)
    if item is None or item.message_id != message.message_id:
        return None
    del pending[message.chat.id]
    return item


def take_draft(chat_id: int, message_id: int) -> Draft | None:
    """Claim a card's Draft for saving; the card stops being a job."""
    draft = drafts.pop((chat_id, message_id), None)
    if draft is None:
        return None
    if _live.get(chat_id) == message_id:
        del _live[chat_id]
    _closed[(chat_id, message_id)] = None
    item = pending.get(chat_id)
    if item is not None and item.message_id == message_id:
        del pending[chat_id]
    return draft


async def _open_card(message: Message, status_text: str, draft: Draft | None) -> Message:
    """The immediate answer: a status line (with 💾 / Cancel for the admin) that becomes the card."""
    status = await message.answer(status_text, reply_markup=draft_menu() if draft else None)
    _live[message.chat.id] = status.message_id
    if draft is not None:
        _remember_draft(message.chat.id, status.message_id, draft)
    return status


async def _fail_card(status: Message, text: str, savable: bool) -> None:
    if not await _still_live(status):
        return
    # A failed card is no job: the chat's earlier pending card, if any, is live again.
    item = pending.get(status.chat.id)
    if item is not None and item.message_id is not None and item.message_id != status.message_id:
        _live[status.chat.id] = item.message_id
    else:
        del _live[status.chat.id]
    await status.edit_text(text, reply_markup=save_only_menu() if savable else None)


_URL_RE = re.compile(r"https?://[^\s<>]+")


def _first_url(text: str | None) -> str | None:
    """First http(s) URL in `text`, trailing sentence punctuation stripped."""
    if not text:
        return None
    match = _URL_RE.search(text)
    return match.group(0).rstrip(").,!?;'\"") if match else None


def _looks_like_link(message: Message) -> bool:
    """Filter: claim a text message only when it carries a URL.

    Keeps this router from swallowing commands (`/settings`, `/status`, …) that
    are handled by routers registered after `documents`.
    """
    return _first_url(message.text) is not None


def is_agent_document(filename: str) -> bool:
    return PurePosixPath(filename.lower()).suffix in ALLOWED_EXTENSIONS


def _accessible(callback: CallbackQuery) -> Message | None:
    """Callback message narrowed to an editable Message (drops Inaccessible)."""
    message = callback.message
    return message if isinstance(message, Message) else None


def _settings_hint(entry: RegistryEntry, effective: dict[str, str]) -> str:
    keys = entry.hint_keys(effective)
    return ", ".join(f"{SETTING_LABELS[key]}={option_label(effective[key])}" for key in keys)


def _prepare(item: Pending, stored: dict[str, str]) -> None:
    """Blocking: preview and price the source for every workflow that accepts it.

    Reuses an existing preview when one is already cached (e.g. "back to job" after a
    settings change) instead of re-fetching over the network on every tap — see the
    security review, L6. Only the estimate, which is settings-dependent, is redone.
    """
    for entry in entries_for(item.source.kind):
        config = entry.build_config(stored)
        preview = item.previews.get(entry.id)
        if preview is None:
            preview = entry.workflow.preview(settings, config, item.source)
            item.previews[entry.id] = preview
        if preview.error:
            item.estimates[entry.id] = Estimate.failed(preview.error)
        else:
            item.estimates[entry.id] = entry.workflow.estimate(settings, config, preview)


def _fmt_cost(value: float) -> str:
    return f"${value:.4f}"


def _fmt_duration(seconds: float) -> str:
    return f"{seconds:.0f}s" if seconds < 60 else f"{int(seconds // 60)} min"


def _card_text(
    item: Pending,
    effective: dict[str, str],
    options: list[ActionOption],
    errors: dict[str, str],
) -> str:
    if isinstance(item.source, DocumentSource):
        head = f"📎 <b>{html.escape(item.title)}</b> ({item.size_bytes / 1024:.0f} KB)"
    else:
        head = f"🎬 <b>{html.escape(item.title)}</b>"
    lines = [head]

    shown = next((item.previews[o.workflow_id] for o in options), None)
    if shown is not None:
        bits = [f"Characters: {shown.char_count}", f"Chapters: {shown.chapter_count}"]
        if shown.duration_s:
            bits.insert(0, f"Duration: {_fmt_duration(shown.duration_s)}")
        lines.append(" · ".join(bits))
        if shown.note:
            lines.append(f"Transcript: {html.escape(shown.note)}")
    lines.append("")

    for opt in options:
        entry = by_id(opt.workflow_id)
        if entry is None:
            continue
        lines.append(f"<b>{html.escape(entry.label)}</b>")
        lines.append(f"• {_settings_hint(entry, effective)}")
    for workflow_id, err in errors.items():
        entry = by_id(workflow_id)
        label = entry.label if entry else workflow_id
        lines.append(f"⚠️ {html.escape(label)} unavailable: {html.escape(err)}")
    return "\n".join(lines)


def _action_options(
    item: Pending, stored: dict[str, str]
) -> tuple[list[ActionOption], dict[str, str]]:
    options: list[ActionOption] = []
    errors: dict[str, str] = {}
    for workflow_id, estimate in item.estimates.items():
        entry = by_id(workflow_id)
        if entry is None:
            continue
        if estimate.error:
            errors[workflow_id] = estimate.error
            continue
        config = entry.build_config(stored)
        preview = item.previews[workflow_id]
        seconds = eta.predict_seconds(workflow_id, config, preview.char_count)
        approx = "≈ " if estimate.approximate else ""
        options.append(
            ActionOption(
                workflow_id=workflow_id,
                label=entry.short_label,
                cost_label=f"{approx}{_fmt_cost(estimate.cost.total_usd)}",
                eta_label=eta.format_eta(seconds),
            )
        )
    return options, errors


async def _spend_block_reason(user_id: int, estimate: Estimate, reserved: float) -> str | None:
    """Why this job must not run, or None; `reserved` is the user's queued + running estimate."""
    cost = estimate.cost.total_usd
    if cost > MAX_JOB_COST_USD:
        return (
            f"This job is estimated at {_fmt_cost(cost)}, over the "
            f"{_fmt_cost(MAX_JOB_COST_USD)} per-job limit. Split the document and send it "
            "in parts."
        )
    if is_admin(user_id):
        return None
    spent = await asyncio.to_thread(db.user_cost_since, user_id, DAILY_COST_WINDOW_HOURS)
    if spent + reserved + cost > DAILY_USER_COST_LIMIT_USD:
        queued = f" plus {_fmt_cost(reserved)} queued" if reserved else ""
        return (
            f"You have spent {_fmt_cost(spent)} in the last {DAILY_COST_WINDOW_HOURS}h{queued}, "
            f"and this job adds {_fmt_cost(cost)}, over the {_fmt_cost(DAILY_USER_COST_LIMIT_USD)} "
            "daily limit. Try again later or ask the owner."
        )
    return None


async def _render_actions(message: Message, user_id: int, item: Pending) -> None:
    stored = await asyncio.to_thread(db.get_user_settings, user_id)
    if not item.estimates:
        try:
            await _run_intake(user_id, _prepare, item, stored)
        except TimeoutError:
            if pending.get(message.chat.id) is item:
                del pending[message.chat.id]
            await _fail_card(
                message, "❌ That took too long to prepare. Please try again.", item.savable
            )
            return
    if not await _still_live(message):
        return
    effective = user_config.effective_settings(stored)
    # _action_options reads the jobs table through eta.predict_seconds — off the loop.
    options, errors = await asyncio.to_thread(_action_options, item, stored)
    if not options:
        if pending.get(message.chat.id) is item:
            del pending[message.chat.id]
        detail = "; ".join(f"{a}: {e}" for a, e in errors.items()) or "unknown error"
        await _fail_card(message, f"❌ Cannot process this: {html.escape(detail)}", item.savable)
        return
    if not await _still_live(message):
        return
    await message.edit_text(
        _card_text(item, effective, options, errors),
        reply_markup=action_menu(options, savable=item.savable),
    )


async def _begin_pending(
    message: Message, source: Source, user_id: int, status_text: str, draft: Draft | None = None
) -> None:
    status = await _open_card(message, status_text, draft)
    item = Pending(source=source, message_id=status.message_id, savable=draft is not None)
    _remember_pending(message.chat.id, item)
    await _render_actions(status, user_id, item)


@router.message(F.document)
async def document_handler(message: Message, bot: Bot) -> None:
    document = message.document
    user = message.from_user
    if document is None or user is None:
        return

    filename = document.file_name or "document"
    if not is_agent_document(filename):
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

    await _begin_pending(message, DocumentSource(file_bytes, filename), user.id, "⏳ Estimating…")


def body_of(message: Message) -> str:
    return (message.text or message.caption or "").strip()


def sender_of(message: Message) -> str | None:
    """Who a forwarded message came from: a person, a hidden user, a chat or a channel."""
    origin = message.forward_origin
    if isinstance(origin, MessageOriginUser):
        return origin.sender_user.full_name
    if isinstance(origin, MessageOriginHiddenUser):
        return origin.sender_user_name
    if isinstance(origin, MessageOriginChat):
        return origin.sender_chat.title or origin.sender_chat.full_name
    if isinstance(origin, MessageOriginChannel):
        return origin.chat.title or origin.chat.full_name
    return None


def draft_of(message: Message) -> Draft:
    """The admin's words and the links hidden behind text in `message`."""
    entities = message.entities or message.caption_entities or []
    links = tuple(e.url for e in entities if e.type == "text_link" and e.url)
    return Draft(
        text=body_of(message),
        links=links,
        sender=sender_of(message),
        message_id=message.message_id,
    )


def is_direct_host(url: str) -> bool:
    """Instagram, YouTube and TikTok links are saved as they are: there is no article to scrape."""
    return is_youtube(url) or is_social_media(url)


def links_of(draft: Draft) -> tuple[str, ...]:
    """Every URL in a Draft, plain and behind text, as notes counts them."""
    return extract_urls(draft.text, linked=draft.links).urls


def card_link(draft: Draft) -> str | None:
    """The one website link that earns the admin a card; anything else is saved straight away."""
    urls = links_of(draft)
    return urls[0] if len(urls) == 1 and not is_direct_host(urls[0]) else None


def is_admin_text(message: Message) -> bool:
    """The admin's non-command text message; a caption belongs to its media."""
    user = message.from_user
    if user is None or not is_admin(user.id) or message.text is None:
        return False
    body = body_of(message)
    return bool(body) and not body.startswith("/")


def _is_admin_input(message: Message) -> bool:
    """The admin's message with exactly one website link: ask what to do with it (ADR-0009)."""
    return is_admin_text(message) and card_link(draft_of(message)) is not None


@router.message(_is_admin_input)
async def admin_input_handler(message: Message) -> None:
    """Admin: a card for one website link — 💾 to notes, the priced agents, or Cancel (ADR-015)."""
    user = message.from_user
    draft = draft_of(message)
    url = card_link(draft)
    if user is None or url is None:
        return
    await offer_link(message, url, user.id, draft)


@router.message(_looks_like_link)
async def link_handler(message: Message) -> None:
    """A pasted link → YouTube goes to the link workflows, anything else is scraped to a document."""
    user = message.from_user
    url = _first_url(message.text)
    if user is None or url is None:
        return
    await offer_link(message, url, user.id)


async def offer_link(message: Message, url: str, user_id: int, draft: Draft | None = None) -> None:
    """Price card for a link in `message`'s chat; with a Draft the card also offers 💾."""
    if _is_youtube_url(url):
        await _begin_pending(message, LinkSource(url), user_id, "📡 Fetching video info…", draft)
        return

    savable = draft is not None
    status = await _open_card(message, "🔗 Fetching the link…", draft)
    try:
        article = await _run_intake(user_id, scrape_url, url)
    except ScrapeError as exc:
        await _fail_card(status, f"❌ {html.escape(str(exc))}", savable)
        return
    except TimeoutError:
        await _fail_card(status, "❌ That took too long to fetch. Please try again.", savable)
        return
    except Exception:
        log.exception("link scrape failed for %s", url)
        await _fail_card(status, "❌ Something went wrong fetching that link.", savable)
        return
    if not await _still_live(status):
        return

    source = DocumentSource(article.markdown.encode("utf-8"), filename_for(article))
    item = Pending(source=source, message_id=status.message_id, savable=savable)
    _remember_pending(message.chat.id, item)
    await status.edit_text("⏳ Estimating…", reply_markup=draft_menu() if savable else None)
    await _render_actions(status, user_id, item)


@router.callback_query(JobCB.filter(F.action == "run"))
async def run_job_handler(callback: CallbackQuery, callback_data: JobCB, queue: JobQueue) -> None:
    message = _accessible(callback)
    item = _pop_pending_for(message) if message else None
    workflow_id = callback_data.workflow
    entry = by_id(workflow_id) if workflow_id else None
    if item is None or message is None or entry is None:
        await callback.answer("This job has expired — send the document again.", show_alert=True)
        return
    offered = item.estimates.get(workflow_id)
    if offered is None or offered.error:
        _remember_pending(message.chat.id, item)
        await callback.answer("That action is unavailable for this document.", show_alert=True)
        return

    user = callback.from_user
    # Serializes this user's estimate -> spend-check -> enqueue: two concurrent Run taps
    # otherwise both read the same "spent so far" and can jointly overshoot the daily
    # cap (see the security review, L1).
    async with _lock_for(_run_locks, user.id):
        if queue.count_for_user(user.id) >= MAX_QUEUED_JOBS_PER_USER:
            _remember_pending(message.chat.id, item)
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
            _remember_pending(message.chat.id, item)
            await callback.answer("That action is unavailable for this document.", show_alert=True)
            return
        if blocked := await _spend_block_reason(user.id, estimate, queue.reserved_cost(user.id)):
            _remember_pending(message.chat.id, item)
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
    drafts.pop((message.chat.id, message.message_id), None)
    await callback.answer()
    suffix = f" · {eta_label}" if eta_label else ""
    text = f"🚀 Starting…{suffix}" if position == 1 else f"⏳ Queued, position {position}{suffix}"
    await message.edit_text(text)


@router.callback_query(JobCB.filter(F.action == "settings"))
async def job_settings_handler(callback: CallbackQuery) -> None:
    message = _accessible(callback)
    if message is None or message.chat.id not in pending:
        await callback.answer("This job has expired — send the document again.", show_alert=True)
        return
    await callback.answer()
    await message.edit_text("⚙️ <b>Settings</b>", reply_markup=root_menu(with_job_back=True))


@router.callback_query(MenuCB.filter(F.page == "job"))
async def back_to_job_handler(callback: CallbackQuery) -> None:
    message = _accessible(callback)
    item = pending.get(message.chat.id) if message else None
    if item is None or message is None or item.message_id != message.message_id:
        await callback.answer("This job has expired — send the document again.", show_alert=True)
        return
    await callback.answer("Re-estimating…")
    # Settings may have changed: previews stay (same source), estimates are rebuilt.
    item.estimates.clear()
    await _render_actions(message, callback.from_user.id, item)


@router.callback_query(JobCB.filter(F.action == "cancel"))
async def cancel_pending_handler(callback: CallbackQuery) -> None:
    message = _accessible(callback)
    if message is not None:
        _pop_pending_for(message)
        drafts.pop((message.chat.id, message.message_id), None)
        _close(message)
        await message.edit_text("✖️ Cancelled")
    await callback.answer()
