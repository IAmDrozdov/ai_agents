"""Workflow config for doc_translator."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from shared.translate import TranslateSpec


class DocTranslatorConfig(BaseModel):
    """Workflow behavior knobs. No env access."""

    # Strict: an unknown config key is a bug.
    model_config = ConfigDict(extra="forbid")

    translation: TranslateSpec = Field(default_factory=TranslateSpec)
    chapter_char_target: int = 8000
    # Backstop against a single document turning into a three-figure bill; the
    # interface's cost cap is the first line, this one cannot be bypassed.
    max_document_chars: int = 2_000_000
