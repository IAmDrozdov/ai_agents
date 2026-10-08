"""Report the chapters a preview already parsed."""

from __future__ import annotations

from langchain_core.runnables import Runnable, RunnableLambda

from shared.config import Settings
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
        chapters = state.get("chapters") or []
        progress.phase("extracting", len(chapters))
        facts = [*state.get("facts", []), Fact("Chapters", str(len(chapters)))]
        return {**state, "facts": facts}

    return RunnableLambda(_run, name="extract_text")
