"""A Voice's Transcript: bytes from the interface's download, text from the shared STT stage."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import openai

from notes.domain.items import Item
from shared.audio import SttSpec, transcribe
from shared.config import settings
from shared.obs import get_logger

log = get_logger(__name__)

# file_id -> bytes; supplied by the interface, so notes never talks to Telegram itself.
Download = Callable[[str], Awaitable[bytes]]


class VoiceError(Exception):
    """Base for everything getting a Transcript can fail with."""


class VoiceUnavailable(VoiceError):
    """Transient: network, rate limit, outage. Worth retrying later."""


class VoiceRejected(VoiceError):
    """Permanent for this Voice: too large to download, unreadable, refused by STT."""


def _filename(item: Item) -> str:
    return "video.mp4" if (item.file_mime or "").startswith("video/") else "voice.ogg"


async def transcript_for(item: Item, download: Download) -> str:
    if not item.file_id:
        raise VoiceRejected("the Voice has no file_id")
    data = await download(item.file_id)
    try:
        result = await asyncio.to_thread(
            transcribe,
            settings,
            data,
            SttSpec(),
            duration_s=float(item.duration_s or 0),
            filename=_filename(item),
        )
    except (openai.RateLimitError, openai.APIConnectionError, openai.InternalServerError) as exc:
        raise VoiceUnavailable(str(exc)) from exc
    except openai.APIStatusError as exc:
        raise VoiceRejected(f"HTTP {exc.status_code}: {exc.message}") from exc
    log.info("item %s: transcribed %ss of audio, $%.5f", item.id, item.duration_s, result.cost.usd)
    return result.text
