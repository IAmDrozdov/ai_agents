"""Parse the document into text and chapters (skipped when a preview already did)."""

from __future__ import annotations

from langchain_core.runnables import Runnable, RunnableLambda

from shared.config import Settings
from shared.doc import DocumentError, parse_document
from shared.job import NO_PROGRESS, Fact, Progress

from ..config import PdfTtsConfig
from ..state import PdfTtsState


def build_extract_text_node(
    settings: Settings, config: PdfTtsConfig, progress: Progress = NO_PROGRESS
) -> Runnable:
    _ = settings

    def _run(state: PdfTtsState) -> dict:
        # Full-state returns: LCEL pipes pass output as the next node's input.
        if state.get("error"):
            return dict(state)
        if not state.get("text"):
            file_bytes = state.get("file_bytes")
            if not file_bytes:
                return {**state, "error": "no file_bytes in state"}
            try:
                parsed = parse_document(
                    file_bytes,
                    state.get("filename") or "document.pdf",
                    chapter_char_target=config.chapter_char_target,
                    max_document_chars=config.max_document_chars,
                )
            except DocumentError as exc:
                return {**state, "error": str(exc)}
            state = {**state, "text": parsed.text, "chapters": parsed.chapters}
        chapters = state.get("chapters") or []
        progress.phase("extracting", len(chapters))
        facts = [*state.get("facts", []), Fact("Chapters", str(len(chapters)))]
        return {**state, "facts": facts}

    return RunnableLambda(_run, name="extract_text")
