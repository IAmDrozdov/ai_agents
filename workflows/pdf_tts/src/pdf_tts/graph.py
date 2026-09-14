# Framework: langchain -- linear document→(translate)→TTS pipeline, no cycles

from __future__ import annotations

from langchain_core.runnables import Runnable

from shared.config import Settings
from shared.job import NO_PROGRESS, Progress

from .config import PdfTtsConfig
from .nodes.extract_text import build_extract_text_node
from .nodes.synthesize_audio import build_synthesize_audio_node
from .nodes.translate import build_translate_node


def build_graph(
    settings: Settings, config: PdfTtsConfig, progress: Progress = NO_PROGRESS
) -> Runnable:
    extract = build_extract_text_node(settings, config, progress)
    translate = build_translate_node(settings, config, progress)
    synthesize = build_synthesize_audio_node(settings, config, progress)
    return extract | translate | synthesize
