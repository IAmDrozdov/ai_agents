"""The workflows the smoke runner can drive."""

from __future__ import annotations

from typing import Any

from doc_translator import WORKFLOW as DOC_TRANSLATOR
from pdf_tts import WORKFLOW as PDF_TTS
from shared.job import Workflow
from yt_dub import WORKFLOW as YT_DUB

WORKFLOWS: dict[str, Workflow[Any]] = {w.id: w for w in (DOC_TRANSLATOR, PDF_TTS, YT_DUB)}
