"""Download audio and transcribe it — only for videos the fetch node found no captions for."""

from __future__ import annotations

from langchain_core.runnables import Runnable, RunnableLambda

from shared.audio import transcribe
from shared.config import Settings
from shared.doc import split_into_chapters
from shared.job import NO_PROGRESS, Progress

from ..config import YtDubConfig
from ..providers.youtube import YouTubeError, download_audio
from ..state import YtDubState

TRANSCRIBED_LABEL = "transcribed audio"


def build_transcribe_node(
    settings: Settings, config: YtDubConfig, progress: Progress = NO_PROGRESS
) -> Runnable:
    def _run(state: YtDubState) -> dict:
        if state.get("error") or not state.get("needs_stt"):
            return dict(state)

        progress.phase("transcribing", 1)
        try:
            audio_bytes, ext = download_audio(
                state.get("url", ""), max_bytes=config.max_audio_bytes_for_stt
            )
        except YouTubeError as exc:
            return {**state, "error": str(exc)}

        duration_s = float(state.get("duration_s") or 0.0)
        result = transcribe(
            settings, audio_bytes, config.stt, duration_s=duration_s, filename=f"audio.{ext}"
        )
        text = result.text
        if not text:
            return {**state, "error": "transcription produced no text"}
        if len(text) > config.max_document_chars:
            return {
                **state,
                "error": (
                    f"Transcript is {len(text):,} characters, over the "
                    f"{config.max_document_chars:,} limit."
                ),
            }

        chapters = split_into_chapters(text, config.chapter_char_target)
        progress.tick(1, 1)
        return {
            **state,
            "text": text,
            "chapters": chapters,
            "transcript_source": TRANSCRIBED_LABEL,
            "needs_stt": False,
            "cost_lines": [*state.get("cost_lines", []), result.cost],
        }

    return RunnableLambda(_run, name="transcribe")
