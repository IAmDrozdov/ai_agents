"""Finalize translated markdown output."""

from __future__ import annotations

from langchain_core.runnables import Runnable, RunnableLambda

from shared.config import Settings
from shared.job import NO_PROGRESS, Progress

from ..config import DocTranslatorConfig
from ..state import DocTranslatorState


def build_finalize_node(
    settings: Settings, config: DocTranslatorConfig, progress: Progress = NO_PROGRESS
) -> Runnable:
    _ = settings
    _ = config
    _ = progress

    def _run(state: DocTranslatorState) -> dict:
        if state.get("error"):
            return dict(state)
        translated_text = state.get("translated_text", "")
        if not translated_text:
            return {**state, "error": "no translated text to finalize"}
        return {**state, "output_markdown": translated_text}

    return RunnableLambda(_run, name="finalize")
