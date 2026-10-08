"""/settings button tree: sections → value pickers, persisted per user."""

from __future__ import annotations

import asyncio
import contextlib
import time
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from shared.audio import SpeechSpec, synthesize
from shared.config import settings

from .. import db, user_config
from ..access import is_admin
from ..cards import CardBook
from ..catalog import (
    DAILY_COST_WINDOW_HOURS,
    DAILY_USER_COST_LIMIT_USD,
    DEFAULTS,
    OPTION_SETS,
    PREVIEW_KEYS,
    SETTING_KEYS,
    SETTING_LABELS,
    TEST_PHRASE,
    coerce_voice,
    option_label,
    voices_for_model,
)
from ..keyboards import (
    MenuCB,
    OptCB,
    SetCB,
    TryCB,
    confirm_menu,
    editable,
    keep_menu,
    options_menu,
    root_menu,
    section_menu,
)

router = Router(name="settings")


@router.message(Command("settings"))
async def settings_command(message: Message) -> None:
    await message.answer("⚙️ <b>Settings</b>", reply_markup=root_menu())


def _job_back(callback: CallbackQuery, cards: CardBook) -> bool:
    message = editable(callback)
    return message is not None and cards.owns_job(message.chat.id, message.message_id)


async def _edit(callback: CallbackQuery, text: str, reply_markup) -> None:
    message = editable(callback)
    if message is None:
        return
    # TelegramBadRequest "message is not modified" — the menu already shows this page.
    with contextlib.suppress(TelegramBadRequest):
        await message.edit_text(text, reply_markup=reply_markup)


@router.callback_query(MenuCB.filter(F.page == "root"))
async def root_page(callback: CallbackQuery, cards: CardBook) -> None:
    await callback.answer()
    await _edit(callback, "⚙️ <b>Settings</b>", root_menu(with_job_back=_job_back(callback, cards)))


@router.callback_query(MenuCB.filter(F.page.in_({"translator", "tts"})))
async def section_page(callback: CallbackQuery, callback_data: MenuCB) -> None:
    stored = await asyncio.to_thread(db.get_user_settings, callback.from_user.id)
    effective = user_config.effective_settings(stored)
    title = (
        "📄 <b>Translator settings</b>"
        if callback_data.page == "translator"
        else "🔊 <b>Audio settings</b>"
    )
    await callback.answer()
    await _edit(callback, title, section_menu(callback_data.page, effective))


@router.callback_query(MenuCB.filter(F.page == "close"))
async def close_page(callback: CallbackQuery) -> None:
    await callback.answer()
    message = editable(callback)
    if message is not None:
        await message.edit_text("⚙️ Settings saved.")


async def _show_option_page(callback: CallbackQuery, key_id: int) -> None:
    key = SETTING_KEYS[key_id]
    stored = await asyncio.to_thread(db.get_user_settings, callback.from_user.id)
    effective = user_config.effective_settings(stored)
    # Voices depend on the chosen speech model — show only valid combinations.
    allowed = voices_for_model(effective["tts.model"]) if key == "tts.voice" else None
    await _edit(
        callback,
        f"Choose <b>{key.split('.', 1)[1].replace('_', ' ')}</b>:",
        options_menu(key_id, effective[key], allowed),
    )


@router.callback_query(OptCB.filter())
async def option_page(callback: CallbackQuery, callback_data: OptCB) -> None:
    await callback.answer()
    await _show_option_page(callback, callback_data.key_id)


def _resolve(key_id: int, idx: int) -> tuple[str, str] | None:
    if not 0 <= key_id < len(SETTING_KEYS):
        return None
    key = SETTING_KEYS[key_id]
    values = OPTION_SETS[key]
    if not 0 <= idx < len(values):
        return None
    return key, values[idx]


async def _persist_and_show_section(callback: CallbackQuery, key: str, value: str) -> None:
    await asyncio.to_thread(db.set_user_setting, callback.from_user.id, key, value)
    stored = await asyncio.to_thread(db.get_user_settings, callback.from_user.id)
    if key == "tts.model":
        # Changing the model can invalidate the stored voice — persist the fix.
        voice = coerce_voice(value, stored.get("tts.voice", DEFAULTS["tts.voice"]))
        if voice != stored.get("tts.voice"):
            await asyncio.to_thread(db.set_user_setting, callback.from_user.id, "tts.voice", voice)
            stored["tts.voice"] = voice
    effective = user_config.effective_settings(stored)
    section = key.split(".", 1)[0]
    title = (
        "📄 <b>Translator settings</b>" if section == "translator" else "🔊 <b>Audio settings</b>"
    )
    await _edit(callback, title, section_menu(section, effective))


@router.callback_query(SetCB.filter())
async def set_value(callback: CallbackQuery, callback_data: SetCB) -> None:
    resolved = _resolve(callback_data.key_id, callback_data.idx)
    if resolved is None:
        await callback.answer("Stale menu — reopen /settings.", show_alert=True)
        return
    key, value = resolved
    if key in PREVIEW_KEYS:
        await callback.answer()
        await _edit(
            callback,
            f"<b>{SETTING_LABELS[key]}</b>: {option_label(value)} — save or hear a test?",
            confirm_menu(callback_data.key_id, callback_data.idx),
        )
        return
    await callback.answer("Saved ✓")
    await _persist_and_show_section(callback, key, value)


# Guards against a second "Test" tap while a synthesis is already running.
_testing: set[tuple[int, int]] = set()

# The test phrase is short, but with no record and no cooldown it was a free-standing
# way to spend outside both caps (see the security review, M5).
_TEST_COOLDOWN_S = 10
_last_test: dict[int, float] = {}


@router.callback_query(TryCB.filter())
async def try_action(callback: CallbackQuery, callback_data: TryCB) -> None:
    resolved = _resolve(callback_data.key_id, callback_data.idx)
    if resolved is None:
        await callback.answer("Stale menu — reopen /settings.", show_alert=True)
        return
    key, value = resolved

    if callback_data.action == "save":
        await callback.answer("Saved ✓")
        await _persist_and_show_section(callback, key, value)
        return
    if callback_data.action == "revert":
        await callback.answer()
        await _show_option_page(callback, callback_data.key_id)
        return

    message = editable(callback)
    if message is None:
        await callback.answer()
        return
    token = (message.chat.id, message.message_id)
    if token in _testing:
        await callback.answer("Already synthesizing…")
        return

    user = callback.from_user
    if not is_admin(user.id):
        now = time.monotonic()
        if now - _last_test.get(user.id, 0.0) < _TEST_COOLDOWN_S:
            await callback.answer("One test at a time — try again in a few seconds.")
            return
        # Unrecorded and unbounded before this check (see the security review, M5):
        # each test costs real money and previously counted toward no cap at all.
        spent = await asyncio.to_thread(db.user_cost_since, user.id, DAILY_COST_WINDOW_HOURS)
        if spent >= DAILY_USER_COST_LIMIT_USD:
            await callback.answer(
                "You've hit your daily spend limit — try a test again tomorrow.",
                show_alert=True,
            )
            return
        _last_test[user.id] = now

    _testing.add(token)
    try:
        await callback.answer("Synthesizing…")
        await _edit(callback, "🔊 Synthesizing test phrase…", None)
        stored = await asyncio.to_thread(db.get_user_settings, user.id)
        # effective_settings() coerces the voice to the pending model.
        effective = user_config.effective_settings({**stored, key: value})
        spec = SpeechSpec(model=effective["tts.model"], voice=effective["tts.voice"])
        error: str | None = None
        audio: bytes | None = None
        duration_s: float | None = None
        try:
            result = await asyncio.to_thread(synthesize, settings, TEST_PHRASE, spec)
            audio = result.audio_bytes
            duration_s = result.audio_duration_s
        except Exception as exc:  # noqa: BLE001 — any TTS failure ends the test, not the bot
            error = str(exc)
        if error or not audio:
            await _edit(
                callback,
                f"⚠️ Test failed: {escape(str(error or 'no audio produced'))}",
                confirm_menu(callback_data.key_id, callback_data.idx),
            )
            return
        job_id = await asyncio.to_thread(
            db.insert_job, user.id, user.username, "tts_test", "test phrase", 0, {}
        )
        await asyncio.to_thread(db.finish_job, job_id, "ok", cost_usd=result.cost.usd)
        duration = round(duration_s) if duration_s else None
        await message.answer_voice(BufferedInputFile(audio, filename="test.ogg"), duration=duration)
        await _edit(
            callback,
            f"<b>{SETTING_LABELS[key]}</b>: {option_label(value)} — keep it?",
            keep_menu(callback_data.key_id, callback_data.idx),
        )
    finally:
        _testing.discard(token)
