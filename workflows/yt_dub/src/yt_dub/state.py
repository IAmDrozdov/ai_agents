"""State carried between yt_dub nodes."""

from __future__ import annotations

from typing_extensions import TypedDict

from shared.job import CostLine, Fact


class YtDubState(TypedDict, total=False):
    url: str
    video_id: str
    title: str
    duration_s: float
    text: str
    translated_text: str
    chapters: list[str]
    # Human label for where the transcript came from (captions or transcribed audio).
    transcript_source: str
    # True once captions have been checked and none exist for a preferred language;
    # the transcribe node then downloads audio and transcribes it.
    needs_stt: bool
    audio_bytes: bytes
    audio_parts: list[bytes]
    audio_format: str
    audio_duration_s: float
    cost_lines: list[CostLine]
    facts: list[Fact]
    error: str | None
