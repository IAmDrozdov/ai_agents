"""Speech-to-text via OpenAI: spec in, typed result with cost out."""

from __future__ import annotations

import io
from dataclasses import dataclass

from pydantic import BaseModel, model_validator

from shared.config import Settings
from shared.job import CostLine
from shared.pricing import STT_MODEL
from shared.translate import build_openai_client

COST_LABEL = "Transcription"


class SttSpec(BaseModel):
    model: str = STT_MODEL.id
    # Billed per minute of audio; the default follows the catalogue.
    price_per_minute: float = 0.0

    @model_validator(mode="after")
    def _price_follows_model(self) -> SttSpec:
        if "price_per_minute" not in self.model_fields_set:
            self.price_per_minute = STT_MODEL.price_per_minute
        return self


@dataclass(frozen=True)
class SttResult:
    text: str
    cost: CostLine


def estimate_transcription(duration_s: float, spec: SttSpec) -> CostLine:
    return CostLine(COST_LABEL, round(duration_s / 60 * spec.price_per_minute, 6))


def transcribe(
    settings: Settings,
    audio_bytes: bytes,
    spec: SttSpec,
    *,
    duration_s: float,
    filename: str = "audio.m4a",
) -> SttResult:
    client = build_openai_client(settings)
    result = client.audio.transcriptions.create(
        model=spec.model,
        file=(filename, io.BytesIO(audio_bytes)),
    )
    return SttResult(text=str(result.text).strip(), cost=estimate_transcription(duration_s, spec))
