"""State carried between doc_translator nodes."""

from __future__ import annotations

from typing_extensions import TypedDict

from shared.job import CostLine, Fact


class DocTranslatorState(TypedDict, total=False):
    file_bytes: bytes
    filename: str
    text: str
    chapters: list[str]
    translated_text: str
    output_markdown: str
    cost_lines: list[CostLine]
    facts: list[Fact]
    error: str | None
