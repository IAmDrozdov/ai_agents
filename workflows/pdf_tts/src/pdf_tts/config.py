"""Workflow config for pdf_tts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.audio import SpeechSpec
from shared.translate import TranslateSpec


class PdfTtsConfig(BaseModel):
    """Workflow behavior knobs. No env access."""

    # Strict: an unknown config key is a bug.
    model_config = ConfigDict(extra="forbid")

    speech: SpeechSpec = Field(default_factory=SpeechSpec)
    translation: TranslateSpec | None = None
    chapter_char_target: int = 8000
    # Backstop against a single document turning into a three-figure bill; the
    # interface's cost cap is the first line, this one cannot be bypassed.
    max_document_chars: int = 2_000_000

    @model_validator(mode="after")
    def _speech_follows_translation(self) -> PdfTtsConfig:
        if self.translation is not None and self.speech.spoken_language is None:
            self.speech = SpeechSpec.model_validate(
                {
                    **self.speech.model_dump(),
                    "spoken_language": self.translation.target_language,
                    "instructions": None,
                }
            )
        return self
