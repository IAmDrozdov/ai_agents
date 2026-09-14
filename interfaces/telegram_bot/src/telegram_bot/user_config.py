"""Map stored per-user settings onto workflow config objects."""

from __future__ import annotations

from typing import Any

from doc_translator.config import DocTranslatorConfig
from pdf_tts.config import PdfTtsConfig
from shared.audio import SpeechSpec
from shared.translate import TranslateSpec
from yt_dub.config import YtDubConfig

from .catalog import DEFAULTS, OPTION_SETS, coerce_voice


def effective_settings(stored: dict[str, str]) -> dict[str, str]:
    """Stored values merged over defaults; stale values fall back to defaults.

    Cross-field rule: the voice must be valid for the chosen speech model
    (tts-1/tts-1-hd accept a subset of gpt-4o-mini-tts voices).
    """
    merged = dict(DEFAULTS)
    for key, value in stored.items():
        if key in OPTION_SETS and value in OPTION_SETS[key]:
            merged[key] = value
    merged["tts.voice"] = coerce_voice(merged["tts.model"], merged["tts.voice"])
    return merged


def build_doc_translator_config(user_settings: dict[str, str]) -> DocTranslatorConfig:
    s = effective_settings(user_settings)
    return DocTranslatorConfig(
        translation=TranslateSpec(
            source_language=s["translator.source_language"],
            target_language=s["translator.target_language"],
            model=s["translator.model"],
        )
    )


def build_pdf_tts_config(user_settings: dict[str, str]) -> PdfTtsConfig:
    s = effective_settings(user_settings)
    translate = s["tts.translate"] == "on"
    return PdfTtsConfig(
        speech=SpeechSpec(model=s["tts.model"], voice=s["tts.voice"]),
        translation=TranslateSpec(
            source_language=s["tts.source_language"],
            target_language=s["tts.target_language"],
            model=DEFAULTS["translator.model"],
        )
        if translate
        else None,
    )


def build_yt_dub_config(user_settings: dict[str, str]) -> YtDubConfig:
    s = effective_settings(user_settings)
    return YtDubConfig(
        speech=SpeechSpec(model=s["tts.model"], voice=s["tts.voice"]),
        translation=TranslateSpec(
            source_language=s["tts.source_language"],
            target_language=s["tts.target_language"],
            model=DEFAULTS["translator.model"],
        ),
    )


def config_snapshot(config: Any) -> dict[str, Any]:
    """Serializable snapshot of the effective workflow config for the usage log."""
    return config.model_dump()
