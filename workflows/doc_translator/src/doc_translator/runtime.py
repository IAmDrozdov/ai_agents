"""doc_translator job descriptor: preview, estimate and run over the shared contract."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import cast

from shared.config import Settings
from shared.doc import DocumentError, parse_document
from shared.job import (
    Cost,
    DocumentSource,
    Estimate,
    FileDeliverable,
    Preview,
    Progress,
    Result,
    Source,
    Workflow,
)
from shared.translate import estimate_translation

from .config import DocTranslatorConfig
from .graph import build_graph
from .state import DocTranslatorState


def preview(settings: Settings, config: DocTranslatorConfig, source: Source) -> Preview:
    _ = settings
    if not isinstance(source, DocumentSource):
        return Preview.failed("document", "doc_translator needs a document, not a link")
    try:
        parsed = parse_document(
            source.file_bytes,
            source.filename,
            chapter_char_target=config.chapter_char_target,
            max_document_chars=config.max_document_chars,
        )
    except DocumentError as exc:
        return Preview.failed(source.filename, str(exc))
    return Preview(
        title=source.filename,
        char_count=parsed.char_count,
        chapter_count=len(parsed.chapters),
        payload={"filename": source.filename, "text": parsed.text, "chapters": parsed.chapters},
    )


def estimate(settings: Settings, config: DocTranslatorConfig, preview: Preview) -> Estimate:
    _ = settings
    if preview.error:
        return Estimate.failed(preview.error)
    chapters = cast(list[str], preview.payload.get("chapters") or [])
    return Estimate(cost=Cost.of(estimate_translation(chapters, config.translation).cost))


def run(
    settings: Settings, config: DocTranslatorConfig, preview: Preview, progress: Progress
) -> Result:
    if preview.error:
        return Result.failed(preview.error)
    initial: DocTranslatorState = {
        "filename": str(preview.payload["filename"]),
        "text": str(preview.payload["text"]),
        "chapters": cast(list[str], preview.payload["chapters"]),
        "cost_lines": [],
        "facts": [],
    }
    state: DocTranslatorState = build_graph(settings, config, progress).invoke(initial)
    cost = Cost.of(*state.get("cost_lines", []))
    if state.get("error"):
        return Result.failed(str(state["error"]), cost)
    stem = PurePosixPath(initial["filename"]).stem
    return Result(
        deliverable=FileDeliverable(
            data=state["translated_text"].encode("utf-8"),
            filename=f"{stem}.translated.md",
        ),
        cost=cost,
        facts=tuple(state.get("facts", [])),
    )


def speed_profile(config: DocTranslatorConfig) -> str:
    return f"doc_translator|{config.translation.model}"


WORKFLOW: Workflow[DocTranslatorConfig] = Workflow(
    id="doc_translator",
    config_type=DocTranslatorConfig,
    accepts=frozenset({"document"}),
    preview=preview,
    estimate=estimate,
    run=run,
    speed_profile=speed_profile,
)
