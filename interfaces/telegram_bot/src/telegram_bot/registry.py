"""The workflows this bot exposes: one entry each, presentation only; behaviour lives in the descriptor."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from doc_translator import WORKFLOW as DOC_TRANSLATOR
from pdf_tts import WORKFLOW as PDF_TTS
from shared.job import SourceKind, Workflow
from yt_dub import WORKFLOW as YT_DUB

from . import user_config


@dataclass(frozen=True)
class RegistryEntry:
    workflow: Workflow[Any]
    label: str
    short_label: str
    # Settings keys worth showing on the estimate card, given the effective settings.
    hint_keys: Callable[[dict[str, str]], list[str]]
    build_config: Callable[[dict[str, str]], BaseModel]

    @property
    def id(self) -> str:
        return self.workflow.id


def _pdf_tts_hint_keys(effective: dict[str, str]) -> list[str]:
    keys = ["tts.model", "tts.voice", "tts.translate"]
    if effective["tts.translate"] == "on":
        keys += ["tts.source_language", "tts.target_language"]
    return keys


REGISTRY: list[RegistryEntry] = [
    RegistryEntry(
        workflow=DOC_TRANSLATOR,
        label="📄 Document Translator",
        short_label="📄 Translate",
        hint_keys=lambda _: [
            "translator.source_language",
            "translator.target_language",
            "translator.model",
        ],
        build_config=user_config.build_doc_translator_config,
    ),
    RegistryEntry(
        workflow=PDF_TTS,
        label="🔊 Document → Audio",
        short_label="🔊 Audio",
        hint_keys=_pdf_tts_hint_keys,
        build_config=user_config.build_pdf_tts_config,
    ),
    RegistryEntry(
        workflow=YT_DUB,
        label="🎬 YouTube → dubbed audio",
        short_label="🎬 Dub",
        # yt_dub always translates (that is the point), so no translate toggle here.
        hint_keys=lambda _: ["tts.model", "tts.voice", "tts.target_language"],
        build_config=user_config.build_yt_dub_config,
    ),
]

BY_ID: dict[str, RegistryEntry] = {entry.id: entry for entry in REGISTRY}


def by_id(workflow_id: str) -> RegistryEntry | None:
    return BY_ID.get(workflow_id)


def label_for(workflow_id: str) -> str:
    return BY_ID[workflow_id].label


def entries_for(kind: SourceKind) -> list[RegistryEntry]:
    return [entry for entry in REGISTRY if kind in entry.workflow.accepts]
