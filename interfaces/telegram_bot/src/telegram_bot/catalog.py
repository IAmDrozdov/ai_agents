"""Bot option lists, defaults, labels, and limits. Prices and model ids come from `shared.pricing`."""

from __future__ import annotations

from shared.config import settings
from shared.pricing import (
    DEFAULT_TRANSLATE_MODEL,
    DEFAULT_TTS_MODEL,
    DEFAULT_TTS_VOICE,
    TRANSLATE_MODELS,
    TTS_MODELS,
    TTS_VOICES,
    coerce_voice,
    model_label,
    voices_for_model,
)

__all__ = ["coerce_voice", "voices_for_model"]


def _languages() -> list[str]:
    """The operator's BOT_LANGUAGES list, with the configured defaults always present."""
    names = [name.strip() for name in settings.bot_languages.split(",") if name.strip()]
    for default in (settings.bot_default_source_language, settings.bot_default_target_language):
        if default not in names:
            names.append(default)
    return names


LANGUAGES = _languages()

# No audio-format option: the bot always synthesizes Opus, because results are
# delivered as voice messages and Telegram only renders those from Ogg/Opus.
OPTION_SETS: dict[str, list[str]] = {
    "translator.source_language": LANGUAGES,
    "translator.target_language": LANGUAGES,
    "translator.model": [m.id for m in TRANSLATE_MODELS],
    "tts.model": [m.id for m in TTS_MODELS],
    "tts.voice": list(TTS_VOICES),
    "tts.translate": ["off", "on"],
    "tts.source_language": LANGUAGES,
    "tts.target_language": LANGUAGES,
}

DEFAULTS: dict[str, str] = {
    "translator.source_language": settings.bot_default_source_language,
    "translator.target_language": settings.bot_default_target_language,
    "translator.model": DEFAULT_TRANSLATE_MODEL,
    "tts.model": DEFAULT_TTS_MODEL,
    "tts.voice": DEFAULT_TTS_VOICE,
    "tts.translate": "off",
    "tts.source_language": settings.bot_default_source_language,
    "tts.target_language": settings.bot_default_target_language,
}

# Ordered key list; callback data carries an index into it (stays <64 bytes).
SETTING_KEYS = list(OPTION_SETS)

# Keys whose picker offers save-or-test instead of saving immediately.
PREVIEW_KEYS = {"tts.model", "tts.voice"}

TEST_PHRASE = "Hi! This is how the selected voice sounds."

SETTING_LABELS: dict[str, str] = {
    "translator.source_language": "Source language",
    "translator.target_language": "Target language",
    "translator.model": "Model",
    "tts.model": "Speech model",
    "tts.voice": "Voice",
    "tts.translate": "Translate first",
    "tts.source_language": "Source language",
    "tts.target_language": "Target language",
}

SECTION_KEYS: dict[str, list[str]] = {
    "translator": [
        "translator.source_language",
        "translator.target_language",
        "translator.model",
    ],
    "tts": [
        "tts.model",
        "tts.voice",
        "tts.translate",
        "tts.source_language",
        "tts.target_language",
    ],
}

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".md", ".markdown", ".txt"}
TG_DOWNLOAD_LIMIT = 20 * 1024 * 1024  # Bot API getFile cap
TG_UPLOAD_LIMIT = 50 * 1024 * 1024  # Bot API send cap

# Spend guards (BOT_* env). A 20 MB text document is ~20M characters, which is a
# three-figure TTS bill, so the priced card alone is not a sufficient brake.
MAX_JOB_COST_USD = settings.bot_max_job_cost_usd
DAILY_USER_COST_LIMIT_USD = settings.bot_daily_user_cost_limit_usd
DAILY_COST_WINDOW_HOURS = 24  # fixed window; edit here for weekly


def option_label(value: str) -> str:
    """Human label for an option value (model ids get friendly names)."""
    return model_label(value)
