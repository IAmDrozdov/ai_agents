"""Inline keyboard builders and callback-data factories."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .catalog import (
    OPTION_SETS,
    SECTION_KEYS,
    SETTING_KEYS,
    SETTING_LABELS,
    option_label,
)


class MenuCB(CallbackData, prefix="m"):
    """Settings-menu navigation: page is 'root', 'translator', 'tts', 'close', 'job'."""

    page: str


class OptCB(CallbackData, prefix="o"):
    """Open the value picker for SETTING_KEYS[key_id]."""

    key_id: int


class SetCB(CallbackData, prefix="s"):
    """Set SETTING_KEYS[key_id] to OPTION_SETS[key][idx]."""

    key_id: int
    idx: int


class TryCB(CallbackData, prefix="t"):
    """Pending voice/model choice: action is 'save', 'test', 'revert'."""

    action: str
    key_id: int
    idx: int


class JobCB(CallbackData, prefix="j"):
    """Pending-job actions: action is 'run', 'settings', 'cancel'."""

    action: str
    workflow: str = ""


@dataclass(frozen=True)
class ActionOption:
    workflow_id: str
    label: str
    cost_label: str
    eta_label: str = ""


def _section_of(key: str) -> str:
    return key.split(".", 1)[0]


def root_menu(*, with_job_back: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📄 Translator", callback_data=MenuCB(page="translator"))
    builder.button(text="🔊 Audio", callback_data=MenuCB(page="tts"))
    if with_job_back:
        builder.button(text="⬅️ Back to job", callback_data=MenuCB(page="job"))
    else:
        builder.button(text="✖️ Close", callback_data=MenuCB(page="close"))
    builder.adjust(2, 1)
    return builder.as_markup()


def section_menu(section: str, values: dict[str, str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for key in SECTION_KEYS[section]:
        label = SETTING_LABELS[key]
        value = option_label(values[key])
        builder.button(
            text=f"{label}: {value}",
            callback_data=OptCB(key_id=SETTING_KEYS.index(key)),
        )
    builder.button(text="⬅️ Back", callback_data=MenuCB(page="root"))
    builder.adjust(1)
    return builder.as_markup()


def options_menu(
    key_id: int, current: str, allowed: Sequence[str] | None = None
) -> InlineKeyboardMarkup:
    key = SETTING_KEYS[key_id]
    builder = InlineKeyboardBuilder()
    for idx, value in enumerate(OPTION_SETS[key]):
        if allowed is not None and value not in allowed:
            continue
        mark = "✅ " if value == current else ""
        builder.button(
            text=f"{mark}{option_label(value)}",
            callback_data=SetCB(key_id=key_id, idx=idx),
        )
    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(text="⬅️ Back", callback_data=MenuCB(page=_section_of(key)).pack())
    )
    return builder.as_markup()


def confirm_menu(key_id: int, idx: int) -> InlineKeyboardMarkup:
    """Save the pending choice, hear a test phrase first, or go back unchanged."""
    builder = InlineKeyboardBuilder()
    builder.button(text="💾 Save", callback_data=TryCB(action="save", key_id=key_id, idx=idx))
    builder.button(text="🔊 Test", callback_data=TryCB(action="test", key_id=key_id, idx=idx))
    builder.button(text="⬅️ Back", callback_data=OptCB(key_id=key_id))
    builder.adjust(2, 1)
    return builder.as_markup()


def keep_menu(key_id: int, idx: int) -> InlineKeyboardMarkup:
    """After a test phrase: keep the pending choice or discard it."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Keep", callback_data=TryCB(action="save", key_id=key_id, idx=idx))
    builder.button(text="↩️ Discard", callback_data=TryCB(action="revert", key_id=key_id, idx=idx))
    builder.adjust(2)
    return builder.as_markup()


def action_menu(options: list[ActionOption]) -> InlineKeyboardMarkup:
    """One button per priced agent; tap runs. Settings + Cancel on the last row."""
    builder = InlineKeyboardBuilder()
    for opt in options:
        parts = [opt.label, opt.cost_label]
        if opt.eta_label:
            parts.append(opt.eta_label)
        builder.button(
            text=" · ".join(parts),
            callback_data=JobCB(action="run", workflow=opt.workflow_id),
        )
    builder.button(text="⚙️ Settings", callback_data=JobCB(action="settings"))
    builder.button(text="✖️ Cancel", callback_data=JobCB(action="cancel"))
    rows = [1] * len(options) + [2]
    builder.adjust(*rows)
    return builder.as_markup()
