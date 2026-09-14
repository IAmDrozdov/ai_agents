"""pdf_tts job descriptor: preview, estimate and run over the shared contract."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import cast

from shared.audio import estimate_speech
from shared.config import Settings
from shared.doc import DocumentError, parse_document
from shared.job import (
    AudioDeliverable,
    Cost,
    CostLine,
    DocumentSource,
    Estimate,
    Preview,
    Progress,
    Result,
    Source,
    Workflow,
)
from shared.translate import TRANSLATION_OUTPUT_CHAR_FACTOR, estimate_translation

from .config import PdfTtsConfig
from .graph import build_graph
from .state import PdfTtsState


def preview(settings: Settings, config: PdfTtsConfig, source: Source) -> Preview:
    _ = settings
    if not isinstance(source, DocumentSource):
        return Preview.failed("document", "pdf_tts needs a document, not a link")
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


def estimate(settings: Settings, config: PdfTtsConfig, preview: Preview) -> Estimate:
    _ = settings
    if preview.error:
        return Estimate.failed(preview.error)
    text = str(preview.payload.get("text") or "")
    chapters = cast(list[str], preview.payload.get("chapters") or [])
    lines: list[CostLine] = []
    spoken = text
    if config.translation is not None:
        lines.append(estimate_translation(chapters, config.translation).cost)
        spoken = "x" * int(len(text) * TRANSLATION_OUTPUT_CHAR_FACTOR)
    lines.append(estimate_speech(spoken, config.speech).cost)
    return Estimate(cost=Cost.of(*lines))


def run(settings: Settings, config: PdfTtsConfig, preview: Preview, progress: Progress) -> Result:
    if preview.error:
        return Result.failed(preview.error)
    initial: PdfTtsState = {
        "filename": str(preview.payload.get("filename") or preview.title),
        "text": str(preview.payload.get("text") or ""),
        "chapters": cast(list[str], preview.payload.get("chapters") or []),
        "cost_lines": [],
        "facts": [],
    }
    state: PdfTtsState = build_graph(settings, config, progress).invoke(initial)
    cost = Cost.of(*state.get("cost_lines", []))
    if state.get("error"):
        return Result.failed(str(state["error"]), cost)
    stem = PurePosixPath(initial["filename"]).stem
    return Result(
        deliverable=AudioDeliverable(
            data=state.get("audio_bytes") or b"",
            filename=f"{stem}.ogg",
            parts=state.get("audio_parts") or [],
            duration_s=float(state.get("audio_duration_s") or 0.0),
        ),
        cost=cost,
        facts=tuple(state.get("facts", [])),
    )


def speed_profile(config: PdfTtsConfig) -> str:
    translate_model = config.translation.model if config.translation else "off"
    return f"pdf_tts|{config.speech.model}|{translate_model}"


WORKFLOW: Workflow[PdfTtsConfig] = Workflow(
    id="pdf_tts",
    config_type=PdfTtsConfig,
    accepts=frozenset({"document"}),
    preview=preview,
    estimate=estimate,
    run=run,
    speed_profile=speed_profile,
)
