"""Provider price catalogue: model ids, labels, prices and voice lists, once."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TranslateModel:
    id: str
    label: str
    input_price_per_1m: float
    output_price_per_1m: float


@dataclass(frozen=True)
class TtsModel:
    id: str
    label: str
    price_per_1k_chars: float
    voices: tuple[str, ...]


@dataclass(frozen=True)
class SttModel:
    id: str
    price_per_minute: float


TTS_VOICES: tuple[str, ...] = (
    "alloy",
    "ash",
    "ballad",
    "cedar",
    "coral",
    "echo",
    "fable",
    "marin",
    "nova",
    "onyx",
    "sage",
    "shimmer",
    "verse",
)

# Verified live (API 400 enums, 2026-07-22): tts-1/tts-1-hd reject
# ballad/cedar/marin/verse; only gpt-4o-mini-tts accepts all 13.
_LEGACY_TTS_VOICES: tuple[str, ...] = (
    "alloy",
    "ash",
    "coral",
    "echo",
    "fable",
    "nova",
    "onyx",
    "sage",
    "shimmer",
)

TRANSLATE_MODELS: tuple[TranslateModel, ...] = (
    TranslateModel("gpt-5.6-luna", "GPT-5.6 Luna (best value)", 1.00, 6.00),
    TranslateModel("gpt-5.6-sol", "GPT-5.6 Sol (premium)", 5.00, 30.00),
    TranslateModel("gpt-4o-mini", "GPT-4o mini (budget)", 0.15, 0.60),
)

TTS_MODELS: tuple[TtsModel, ...] = (
    TtsModel("gpt-4o-mini-tts", "GPT-4o mini TTS (steerable)", 0.015, TTS_VOICES),
    TtsModel("tts-1-hd", "TTS-1 HD", 0.030, _LEGACY_TTS_VOICES),
    TtsModel("tts-1", "TTS-1", 0.015, _LEGACY_TTS_VOICES),
)

STT_MODEL = SttModel("gpt-4o-mini-transcribe", 0.003)

DEFAULT_TRANSLATE_MODEL = "gpt-5.6-luna"
DEFAULT_TTS_MODEL = "gpt-4o-mini-tts"
DEFAULT_TTS_VOICE = "marin"
FALLBACK_TTS_VOICE = "nova"

TRANSLATE_MODELS_BY_ID: dict[str, TranslateModel] = {m.id: m for m in TRANSLATE_MODELS}
TTS_MODELS_BY_ID: dict[str, TtsModel] = {m.id: m for m in TTS_MODELS}
MODEL_LABELS: dict[str, str] = {
    **{m.id: m.label for m in TRANSLATE_MODELS},
    **{m.id: m.label for m in TTS_MODELS},
}


def translate_prices(model: str) -> tuple[float, float]:
    """USD per 1M input/output tokens; unknown ids price as the default model."""
    entry = TRANSLATE_MODELS_BY_ID.get(model, TRANSLATE_MODELS_BY_ID[DEFAULT_TRANSLATE_MODEL])
    return entry.input_price_per_1m, entry.output_price_per_1m


def tts_price(model: str) -> float:
    """USD per 1k synthesized characters; unknown ids price as the default model."""
    return TTS_MODELS_BY_ID.get(model, TTS_MODELS_BY_ID[DEFAULT_TTS_MODEL]).price_per_1k_chars


def voices_for_model(model: str) -> tuple[str, ...]:
    return TTS_MODELS_BY_ID.get(model, TTS_MODELS_BY_ID[DEFAULT_TTS_MODEL]).voices


def coerce_voice(model: str, voice: str) -> str:
    """Voice valid for the model, falling back when the combo is unsupported."""
    return voice if voice in voices_for_model(model) else FALLBACK_TTS_VOICE


def model_label(model_id: str) -> str:
    return MODEL_LABELS.get(model_id, model_id)
