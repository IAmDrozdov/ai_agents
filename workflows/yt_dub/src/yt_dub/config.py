"""Workflow config for yt_dub."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.audio import SpeechSpec, SttSpec
from shared.translate import TranslateSpec


class YtDubConfig(BaseModel):
    """Workflow behavior knobs. No env access."""

    # Strict: an unknown config key is a bug.
    model_config = ConfigDict(extra="forbid")

    speech: SpeechSpec = Field(default_factory=SpeechSpec)
    translation: TranslateSpec = Field(default_factory=TranslateSpec)
    stt: SttSpec = Field(default_factory=SttSpec)
    chapter_char_target: int = 8000
    # Backstop against a single transcript turning into a three-figure bill; the
    # interface's cost cap is the first line, this one cannot be bypassed.
    max_document_chars: int = 2_000_000
    # OpenAI's transcription input cap. Downloaded audio over this size fails
    # outright rather than being split — splitting needs ffmpeg, which this
    # deployment deliberately does not have (ADR-008).
    max_audio_bytes_for_stt: int = 25 * 1024 * 1024
    max_video_duration_s: int = 4 * 3600
    # Caption languages to try, in addition to the video's own detected language
    # (tried first). See providers/youtube.py::fetch_captions.
    caption_languages: list[str] = ["en"]
    # Speech runs roughly 900 characters/minute; used only to estimate the cost of a
    # no-captions video before its audio has actually been transcribed.
    chars_per_minute_estimate: int = 900

    @model_validator(mode="after")
    def _speech_follows_translation(self) -> YtDubConfig:
        if self.speech.spoken_language is None:
            self.speech = SpeechSpec.model_validate(
                {
                    **self.speech.model_dump(),
                    "spoken_language": self.translation.target_language,
                    "instructions": None,
                }
            )
        return self
