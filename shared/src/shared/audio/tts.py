"""Parallel text-to-speech via OpenAI: spec in, typed result with cost out."""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, model_validator

from shared.config import Settings
from shared.job import CostLine
from shared.obs import get_logger
from shared.pricing import DEFAULT_TTS_MODEL, DEFAULT_TTS_VOICE, coerce_voice, tts_price
from shared.translate import build_openai_client

from .ogg_opus import OggOpusError
from .ogg_opus import concat as concat_ogg_opus

log = get_logger(__name__)

COST_LABEL = "Speech"

INSTRUCTABLE_MODELS = {
    "gpt-4o-mini-tts",
    "gpt-4o-mini-tts-2025-03-20",
    "gpt-4o-mini-tts-2025-12-15",
}

TTS_TIMEOUT_S = 180.0

FORMAT_MIME: dict[str, str] = {
    "mp3": "mpeg",
    "opus": "ogg",
    "aac": "aac",
    "flac": "flac",
}


class SpeechSpec(BaseModel):
    """Everything the speech stage needs; voice and price follow the model unless set."""

    model: str = DEFAULT_TTS_MODEL
    voice: str = DEFAULT_TTS_VOICE
    # Language the text is in; drives the default instructions. None = unknown.
    spoken_language: str | None = None
    instructions: str | None = None
    # 3500 keeps headroom under the API's 4096-char cap and gpt-4o-mini-tts's
    # ~2000-token input ceiling for dense non-Latin scripts.
    chunk_size: int = 3500
    output_format: Literal["mp3", "opus", "aac", "flac"] = "opus"
    max_parallel: int = 4
    # Per-chunk blobs are only useful to a caller that has to split a large result.
    # Below this size the joined blob is enough, and holding both doubles peak RAM.
    retain_parts_over_bytes: int = 40 * 1024 * 1024
    price_per_1k_chars: float = 0.0

    @model_validator(mode="after")
    def _defaults_follow_model(self) -> SpeechSpec:
        self.voice = coerce_voice(self.model, self.voice)
        if "price_per_1k_chars" not in self.model_fields_set:
            self.price_per_1k_chars = tts_price(self.model)
        if self.instructions is None:
            lead = f"Speak in {self.spoken_language}. " if self.spoken_language else ""
            self.instructions = f"{lead}Clear, natural pronunciation. Calm, measured pace."
        return self


@dataclass(frozen=True)
class TtsEstimate:
    chars_billed: int
    chunk_count: int
    cost: CostLine


@dataclass(frozen=True)
class TtsResult:
    audio_bytes: bytes
    audio_parts: list[bytes]
    audio_format: str
    audio_duration_s: float
    chars_billed: int
    chunk_count: int
    duration_s: float
    cost: CostLine


def chunk_text(text: str, chunk_size: int) -> list[str]:
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= chunk_size:
            chunks.append(remaining)
            break
        split_at = remaining.rfind(" ", 0, chunk_size)
        if split_at == -1:
            split_at = chunk_size
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip()
    return chunks


def estimate_speech(text: str, spec: SpeechSpec) -> TtsEstimate:
    if not text:
        return TtsEstimate(0, 0, CostLine(COST_LABEL, 0.0))
    chunks = chunk_text(text, spec.chunk_size)
    chars_billed = sum(len(chunk) for chunk in chunks)
    return TtsEstimate(
        chars_billed=chars_billed,
        chunk_count=len(chunks),
        cost=CostLine(COST_LABEL, round(chars_billed / 1000 * spec.price_per_1k_chars, 6)),
    )


def _call_openai_tts(idx: int, chunk: str, client: Any, spec: SpeechSpec) -> tuple[int, bytes]:
    log.info("tts.synthesize: chunk %d (%d chars)", idx + 1, len(chunk))
    kwargs: dict[str, Any] = {
        "model": spec.model,
        "voice": spec.voice,
        "input": chunk,
        "response_format": spec.output_format,
    }
    if spec.model in INSTRUCTABLE_MODELS and spec.instructions:
        kwargs["instructions"] = spec.instructions
    response = client.audio.speech.create(**kwargs)
    return idx, response.content


def _join(blobs: list[bytes], output_format: str) -> tuple[bytes, float]:
    """Combine per-chunk TTS blobs into one file, plus its duration in seconds.

    Opus gets real container stitching: each chunk is a standalone Ogg stream, and a
    plain byte join would leave a *chained* file whose duration and seek bar only
    reflect chunk 1. Other formats keep the naive join (MP3 tolerates it) and report
    an unknown duration of 0.0.
    """
    if output_format != "opus":
        return b"".join(blobs), 0.0
    try:
        return concat_ogg_opus(blobs)
    except OggOpusError:
        # Degrade rather than lose the whole synthesis run: callers treat a 0.0
        # duration as "unknown" and pick a delivery method that does not need it.
        log.warning("tts.synthesize: opus stitching failed, falling back to byte join")
        return b"".join(blobs), 0.0


def synthesize(
    settings: Settings,
    text: str,
    spec: SpeechSpec,
    on_progress: Callable[[int, int], None] | None = None,
) -> TtsResult:
    """Synthesize `text` chunked and in parallel; on the first failure, cancel the rest and re-raise."""
    # Synthesis of a full chunk takes longer than a chat completion, so it gets a more
    # generous deadline than the shared default.
    client = build_openai_client(settings, timeout=TTS_TIMEOUT_S)

    chunks = chunk_text(text, spec.chunk_size)
    total = len(chunks)
    results: list[bytes | None] = [None] * total
    chars_billed = 0
    done_count = 0
    t0 = time.perf_counter()

    pool = ThreadPoolExecutor(max_workers=spec.max_parallel)
    first_error: BaseException | None = None
    try:
        futures = {
            pool.submit(_call_openai_tts, i, chunk, client, spec): i
            for i, chunk in enumerate(chunks)
        }
        for future in as_completed(futures):
            try:
                idx, chunk_bytes = future.result()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
                    # Chunks not yet started are cancellable; every one cancelled here
                    # is a request we do not pay for.
                    for pending in futures:
                        pending.cancel()
                continue
            results[idx] = chunk_bytes
            chars_billed += len(chunks[idx])
            done_count += 1
            if on_progress:
                on_progress(done_count, total)
    finally:
        pool.shutdown(wait=True, cancel_futures=True)

    if first_error is not None:
        log.warning(
            "tts.synthesize: aborted after %d/%d chunks (%d chars billed)",
            done_count,
            total,
            chars_billed,
        )
        raise first_error

    blobs = [part for part in results if part is not None]
    audio_bytes, audio_duration_s = _join(blobs, spec.output_format)
    duration_s = time.perf_counter() - t0
    usd = round(chars_billed / 1000 * spec.price_per_1k_chars, 6)

    log.info(
        "tts.synthesize: done %d bytes, %.1fs audio, %.2fs, $%.4f",
        len(audio_bytes),
        audio_duration_s,
        duration_s,
        usd,
    )
    return TtsResult(
        audio_bytes=audio_bytes,
        audio_parts=blobs if len(audio_bytes) > spec.retain_parts_over_bytes else [],
        audio_format=FORMAT_MIME.get(spec.output_format, spec.output_format),
        audio_duration_s=audio_duration_s,
        chars_billed=chars_billed,
        chunk_count=total,
        duration_s=round(duration_s, 3),
        cost=CostLine(COST_LABEL, usd),
    )
