"""Shared audio stages: speech synthesis, Ogg/Opus container stitching, transcription."""

from shared.audio.ogg_opus import OggOpusError
from shared.audio.ogg_opus import concat as concat_ogg_opus
from shared.audio.stt import SttResult, SttSpec, estimate_transcription, transcribe
from shared.audio.tts import (
    INSTRUCTABLE_MODELS,
    TTS_TIMEOUT_S,
    SpeechSpec,
    TtsEstimate,
    TtsResult,
    chunk_text,
    estimate_speech,
    synthesize,
)

__all__ = [
    "INSTRUCTABLE_MODELS",
    "TTS_TIMEOUT_S",
    "OggOpusError",
    "SpeechSpec",
    "SttResult",
    "SttSpec",
    "TtsEstimate",
    "TtsResult",
    "chunk_text",
    "concat_ogg_opus",
    "estimate_speech",
    "estimate_transcription",
    "synthesize",
    "transcribe",
]
