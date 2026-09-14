# Framework: langchain -- linear extract→translate→finalize pipeline, no cycles

from __future__ import annotations

from langchain_core.runnables import Runnable

from shared.config import Settings
from shared.job import NO_PROGRESS, Progress

from .config import DocTranslatorConfig
from .nodes.extract_text import build_extract_text_node
from .nodes.finalize import build_finalize_node
from .nodes.translate import build_translate_node


def build_graph(
    settings: Settings, config: DocTranslatorConfig, progress: Progress = NO_PROGRESS
) -> Runnable:
    extract = build_extract_text_node(settings, config, progress)
    translate = build_translate_node(settings, config, progress)
    finalize = build_finalize_node(settings, config, progress)
    return extract | translate | finalize
