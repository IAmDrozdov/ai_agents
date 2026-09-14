# Framework: langchain -- linear YouTube→transcript→translate→TTS pipeline, no cycles

from __future__ import annotations

from langchain_core.runnables import Runnable

from shared.config import Settings
from shared.job import NO_PROGRESS, Progress

from .config import YtDubConfig
from .nodes.fetch_transcript import build_fetch_transcript_node
from .nodes.synthesize_audio import build_synthesize_audio_node
from .nodes.transcribe import build_transcribe_node
from .nodes.translate import build_translate_node


def build_graph(
    settings: Settings, config: YtDubConfig, progress: Progress = NO_PROGRESS
) -> Runnable:
    fetch = build_fetch_transcript_node(settings, config, progress)
    transcribe = build_transcribe_node(settings, config, progress)
    translate = build_translate_node(settings, config, progress)
    synthesize = build_synthesize_audio_node(settings, config, progress)
    return fetch | transcribe | translate | synthesize
