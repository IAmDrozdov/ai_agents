"""State carried between pdf_tts nodes."""

from __future__ import annotations

from typing_extensions import TypedDict

from shared.job import CostLine, Fact


class PdfTtsState(TypedDict, total=False):
    file_bytes: bytes
    filename: str
    text: str
    chapters: list[str]
    translated_text: str
    audio_bytes: bytes
    audio_parts: list[bytes]
    audio_format: str
    # Playable length of `audio_bytes`; 0.0 when unknown (only Opus is measured).
    audio_duration_s: float
    cost_lines: list[CostLine]
    facts: list[Fact]
    error: str | None
