"""Fetch a YouTube video's transcript from captions, when available.

Never downloads audio and never calls a paid API — safe to run the moment a link is
pasted, before the user has confirmed anything. With no caption track in a preferred
language it sets `needs_stt` and leaves audio download + STT to the transcribe node.
"""

from __future__ import annotations

from langchain_core.runnables import Runnable, RunnableLambda

from shared.config import Settings
from shared.doc import split_into_chapters
from shared.job import NO_PROGRESS, Progress
from shared.obs import get_logger

from ..config import YtDubConfig
from ..providers.youtube import YouTubeError, extract_info, fetch_captions, meta_from_info
from ..state import YtDubState

log = get_logger(__name__)

SOURCE_LABELS = {"subtitles": "subtitles", "auto_captions": "auto-generated captions"}
PENDING_STT_LABEL = "no captions — will transcribe audio"


def _preferred_langs(meta_language: str | None, configured: list[str]) -> list[str]:
    langs: list[str] = []
    if meta_language:
        langs.append(meta_language)
    for lang in configured:
        if lang not in langs:
            langs.append(lang)
    return langs


def build_fetch_transcript_node(
    settings: Settings, config: YtDubConfig, progress: Progress = NO_PROGRESS
) -> Runnable:
    _ = settings

    def _run(state: YtDubState) -> dict:
        if state.get("error"):
            return dict(state)
        if state.get("video_id"):
            # A preview already fetched this; nothing to redo.
            return dict(state)

        url = state.get("url", "")
        if not url:
            return {**state, "error": "no URL to fetch"}

        progress.phase("fetching", 1)
        try:
            info = extract_info(url)
        except YouTubeError as exc:
            return {**state, "error": str(exc)}

        # meta_from_info() coerces a missing duration to 0.0, which would otherwise
        # sail through the duration cap below and price at $0 (M1). Check the raw
        # info dict instead, before that coercion happens.
        not_a_video = info.get("_type", "video") != "video"
        if not_a_video or info.get("is_live") or info.get("duration") is None:
            return {
                **state,
                "error": (
                    "This YouTube result has no fixed duration (a live stream or a "
                    "non-video result) and is not supported."
                ),
            }

        meta = meta_from_info(info)
        if meta.duration_s > config.max_video_duration_s:
            return {
                **state,
                "error": (
                    f"Video is {meta.duration_s / 60:.0f} min, over the "
                    f"{config.max_video_duration_s / 60:.0f} min limit."
                ),
            }

        base = {
            **state,
            "video_id": meta.video_id,
            "title": meta.title,
            "duration_s": meta.duration_s,
        }

        preferred = _preferred_langs(meta.language, config.caption_languages)
        try:
            found = fetch_captions(info, preferred=preferred)
        except YouTubeError as exc:
            return {**base, "error": str(exc)}

        if found is None:
            log.info("yt_dub: no captions for %s, needs STT", meta.video_id)
            return {**base, "needs_stt": True, "transcript_source": PENDING_STT_LABEL}

        text, source = found
        if len(text) > config.max_document_chars:
            return {
                **base,
                "error": (
                    f"Transcript is {len(text):,} characters, over the "
                    f"{config.max_document_chars:,} limit."
                ),
            }

        chapters = split_into_chapters(text, config.chapter_char_target)
        log.info("yt_dub: %s for %s (%d chars)", SOURCE_LABELS[source], meta.video_id, len(text))
        return {
            **base,
            "text": text,
            "chapters": chapters,
            "transcript_source": SOURCE_LABELS[source],
            "needs_stt": False,
        }

    return RunnableLambda(_run, name="fetch_transcript")
