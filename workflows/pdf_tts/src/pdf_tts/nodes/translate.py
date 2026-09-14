"""Translate chapters before synthesis, when the config asks for it."""

from __future__ import annotations

from langchain_core.runnables import Runnable, RunnableLambda

from shared.config import Settings
from shared.job import NO_PROGRESS, Fact, Progress
from shared.translate import translate_chunks

from ..config import PdfTtsConfig
from ..state import PdfTtsState


def build_translate_node(
    settings: Settings, config: PdfTtsConfig, progress: Progress = NO_PROGRESS
) -> Runnable:
    def _run(state: PdfTtsState) -> dict:
        if state.get("error"):
            return dict(state)
        spec = config.translation
        if spec is None:
            return dict(state)

        chapters = state.get("chapters") or []
        if not chapters:
            return {**state, "error": "no chapters to translate"}

        progress.phase("translating", len(chapters))
        result = translate_chunks(settings, chapters, spec, on_progress=progress.tick)
        merged = "\n\n".join(result.chunks)
        if not merged:
            return {**state, "error": "translation produced no text"}

        return {
            **state,
            "text": merged,
            "translated_text": merged,
            "chapters": result.chunks,
            "cost_lines": [*state.get("cost_lines", []), result.cost],
            "facts": [
                *state.get("facts", []),
                Fact("Tokens", f"{result.input_tokens} in / {result.output_tokens} out"),
            ],
        }

    return RunnableLambda(_run, name="translate")
