"""Synthesize the (possibly translated) text via the shared speech stage."""

from __future__ import annotations

from langchain_core.runnables import Runnable, RunnableLambda

from shared.audio import chunk_text, synthesize
from shared.config import Settings
from shared.job import NO_PROGRESS, Fact, Progress

from ..config import PdfTtsConfig
from ..state import PdfTtsState


def build_synthesize_audio_node(
    settings: Settings, config: PdfTtsConfig, progress: Progress = NO_PROGRESS
) -> Runnable:
    def _run(state: PdfTtsState) -> dict:
        if state.get("error"):
            return dict(state)

        text = state.get("text", "")
        if not text:
            return {**state, "error": "no text to synthesize"}

        spec = config.speech
        progress.phase("synthesizing", len(chunk_text(text, spec.chunk_size)))
        result = synthesize(settings, text, spec, on_progress=progress.tick)

        return {
            **state,
            "audio_bytes": result.audio_bytes,
            "audio_parts": result.audio_parts,
            "audio_format": result.audio_format,
            "audio_duration_s": result.audio_duration_s,
            "cost_lines": [*state.get("cost_lines", []), result.cost],
            "facts": [
                *state.get("facts", []),
                Fact("Chars billed", str(result.chars_billed)),
                Fact("Chunks", str(result.chunk_count)),
                Fact("Synthesis", f"{result.duration_s:.0f}s"),
            ],
        }

    return RunnableLambda(_run, name="synthesize_audio")
