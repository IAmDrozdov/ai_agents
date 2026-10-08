"""yt_dub job descriptor: preview, estimate and run over the shared contract."""

from __future__ import annotations

import re
from typing import cast

from shared.audio import estimate_speech, estimate_transcription
from shared.config import Settings
from shared.job import (
    AudioDeliverable,
    Cost,
    CostLine,
    Estimate,
    LinkSource,
    Preview,
    Progress,
    Result,
    Source,
    Workflow,
)
from shared.translate import TRANSLATION_OUTPUT_CHAR_FACTOR, estimate_translation

from .config import YtDubConfig
from .graph import build_graph
from .nodes.fetch_transcript import build_fetch_transcript_node
from .state import YtDubState

_UNSAFE_FILENAME = re.compile(r"[^\w\s.-]+", re.UNICODE)


def _stem(title: str) -> str:
    cleaned = _UNSAFE_FILENAME.sub("", title).strip() or "video"
    return cleaned[:80]


def preview(settings: Settings, config: YtDubConfig, source: Source) -> Preview:
    """Captions-only look: no audio download, no paid API call."""
    if not isinstance(source, LinkSource):
        return Preview.failed("video", "yt_dub needs a YouTube link, not a document")
    fetch = build_fetch_transcript_node(settings, config)
    state: YtDubState = fetch.invoke({"url": source.url})
    title = str(state.get("title") or "video")
    if state.get("error"):
        return Preview.failed(title, str(state["error"]))
    text = str(state.get("text") or "")
    return Preview(
        title=title,
        char_count=len(text),
        chapter_count=len(state.get("chapters") or []),
        duration_s=float(state.get("duration_s") or 0.0),
        note=str(state.get("transcript_source") or ""),
        payload=cast(dict[str, object], dict(state)),
    )


def estimate(settings: Settings, config: YtDubConfig, preview: Preview) -> Estimate:
    _ = settings
    if preview.error:
        return Estimate.failed(preview.error)
    duration_s = cast(float, preview.duration_s)
    lines: list[CostLine] = []
    approximate = False
    if preview.payload.get("needs_stt"):
        # No captions: estimate from duration alone, nothing has been transcribed yet.
        approx_chars = int(duration_s / 60 * config.chars_per_minute_estimate)
        text = "x" * approx_chars
        chapters: list[str] = [text] if text else []
        lines.append(estimate_transcription(duration_s, config.stt))
        approximate = True
    else:
        text = str(preview.payload.get("text") or "")
        chapters = cast(list[str], preview.payload.get("chapters") or [])
    lines.append(estimate_translation(chapters, config.translation).cost)
    spoken = "x" * int(len(text) * TRANSLATION_OUTPUT_CHAR_FACTOR)
    lines.append(estimate_speech(spoken, config.speech).cost)
    return Estimate(cost=Cost.of(*lines), approximate=approximate)


def run(settings: Settings, config: YtDubConfig, preview: Preview, progress: Progress) -> Result:
    if preview.error:
        return Result.failed(preview.error)
    initial = cast(YtDubState, {**preview.payload, "cost_lines": [], "facts": []})
    state: YtDubState = build_graph(settings, config, progress).invoke(initial)
    cost = Cost.of(*state.get("cost_lines", []))
    if state.get("error"):
        return Result.failed(str(state["error"]), cost)
    return Result(
        deliverable=AudioDeliverable(
            data=state["audio_bytes"],
            filename=f"{_stem(preview.title)}.ogg",
            parts=state.get("audio_parts") or [],
            duration_s=float(state.get("audio_duration_s") or 0.0),
        ),
        cost=cost,
        facts=tuple(state.get("facts", [])),
    )


def speed_profile(config: YtDubConfig) -> str:
    return f"yt_dub|{config.speech.model}|{config.translation.model}"


WORKFLOW: Workflow[YtDubConfig] = Workflow(
    id="yt_dub",
    config_type=YtDubConfig,
    accepts=frozenset({"link"}),
    preview=preview,
    estimate=estimate,
    run=run,
    speed_profile=speed_profile,
)
