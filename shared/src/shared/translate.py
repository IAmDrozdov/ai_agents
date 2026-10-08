"""Parallel document translation via OpenAI chat: spec in, typed result with cost out."""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, model_validator

from shared.config import Settings
from shared.job import CostLine
from shared.obs import get_logger
from shared.pricing import DEFAULT_TRANSLATE_MODEL, translate_prices

log = get_logger(__name__)

COST_LABEL = "Translation"
CHARS_PER_TOKEN_ESTIMATE = 4
TRANSLATION_OUTPUT_CHAR_FACTOR = 1.1

# The SDK default is 600s x 3 attempts. The bot runs one job at a time, so a hung
# request holds up every queued user; fail fast instead.
OPENAI_TIMEOUT_S = 90.0
OPENAI_MAX_RETRIES = 3

# Nothing bounded a single completion's length, so a chunk that got the model to
# repeat itself priced far above its estimate (see the security review, M3). Each
# request is capped relative to what that chunk should plausibly produce, and the
# whole job aborts if real spend still outruns its estimate by this multiple.
MAX_COMPLETION_TOKENS_CAP = 16_384
COST_CEILING_MULTIPLIER = 3.0
MIN_COST_CEILING_USD = 0.20


class TranslateSpec(BaseModel):
    """Everything the translation stage needs; prices follow the model unless set."""

    source_language: str = "English"
    target_language: str = "Russian"
    model: str = DEFAULT_TRANSLATE_MODEL
    max_parallel: int = 4
    input_price_per_1m: float = 0.0
    output_price_per_1m: float = 0.0

    @model_validator(mode="after")
    def _prices_follow_model(self) -> TranslateSpec:
        default_in, default_out = translate_prices(self.model)
        if "input_price_per_1m" not in self.model_fields_set:
            self.input_price_per_1m = default_in
        if "output_price_per_1m" not in self.model_fields_set:
            self.output_price_per_1m = default_out
        return self


@dataclass(frozen=True)
class TranslateEstimate:
    input_tokens: int
    output_tokens: int
    cost: CostLine


@dataclass(frozen=True)
class TranslateResult:
    chunks: list[str]
    duration_s: float
    input_tokens: int
    output_tokens: int
    cost: CostLine


def cost_usd(spec: TranslateSpec, input_tokens: int, output_tokens: int) -> float:
    return round(
        input_tokens / 1_000_000 * spec.input_price_per_1m
        + output_tokens / 1_000_000 * spec.output_price_per_1m,
        6,
    )


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // CHARS_PER_TOKEN_ESTIMATE)


def system_prompt(spec: TranslateSpec) -> str:
    return (
        f"Translate from {spec.source_language} to {spec.target_language}. "
        "Preserve meaning, structure, and formatting. "
        "Output only the translation."
    )


def estimate_translation(chapters: list[str], spec: TranslateSpec) -> TranslateEstimate:
    """Pre-flight estimate that prices the same prompt `translate_chunks` sends."""
    if not chapters:
        return TranslateEstimate(0, 0, CostLine(COST_LABEL, 0.0))
    prompt_tokens = estimate_tokens(system_prompt(spec))
    input_tokens = sum(prompt_tokens + estimate_tokens(chapter) for chapter in chapters)
    output_chars = int(sum(len(chapter) for chapter in chapters) * TRANSLATION_OUTPUT_CHAR_FACTOR)
    output_tokens = max(1, output_chars // CHARS_PER_TOKEN_ESTIMATE) if output_chars else 0
    return TranslateEstimate(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=CostLine(COST_LABEL, cost_usd(spec, input_tokens, output_tokens)),
    )


def build_openai_client(
    settings: Settings,
    *,
    timeout: float = OPENAI_TIMEOUT_S,
    max_retries: int = OPENAI_MAX_RETRIES,
) -> Any:
    """OpenAI client with an explicit deadline, shared by every workflow."""
    import openai

    raw_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
    return openai.OpenAI(api_key=raw_key, timeout=timeout, max_retries=max_retries)


def _translate_one(
    idx: int,
    chunk: str,
    client: Any,
    spec: TranslateSpec,
) -> tuple[int, str, int, int]:
    prompt = system_prompt(spec)
    log.info("translate_chunks: chapter %d (%d chars)", idx + 1, len(chunk))
    expected_output_tokens = max(
        1, int(len(chunk) * TRANSLATION_OUTPUT_CHAR_FACTOR) // CHARS_PER_TOKEN_ESTIMATE
    )
    max_completion_tokens = min(MAX_COMPLETION_TOKENS_CAP, 2 * expected_output_tokens + 256)
    response = client.chat.completions.create(
        model=spec.model,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": chunk},
        ],
        max_completion_tokens=max_completion_tokens,
    )
    choice = response.choices[0]
    if getattr(choice, "finish_reason", None) == "length":
        raise RuntimeError(
            f"Chapter {idx + 1} hit the {max_completion_tokens}-token completion cap and came "
            "back truncated. Lower chapter_char_target, or raise MAX_COMPLETION_TOKENS_CAP."
        )
    content = choice.message.content or ""
    usage = getattr(response, "usage", None)
    if (
        usage is not None
        and usage.prompt_tokens is not None
        and usage.completion_tokens is not None
    ):
        return idx, content.strip(), int(usage.prompt_tokens), int(usage.completion_tokens)

    input_tokens = estimate_tokens(prompt) + estimate_tokens(chunk)
    output_tokens = estimate_tokens(content)
    return idx, content.strip(), input_tokens, output_tokens


def translate_chunks(
    settings: Settings,
    chunks: list[str],
    spec: TranslateSpec,
    on_progress: Callable[[int, int], None] | None = None,
) -> TranslateResult:
    """Translate in parallel; on the first failure, cancel the rest and re-raise it."""
    if not chunks:
        return TranslateResult([], 0.0, 0, 0, CostLine(COST_LABEL, 0.0))

    client = build_openai_client(settings)
    total = len(chunks)
    results: list[str | None] = [None] * total
    input_tokens = 0
    output_tokens = 0
    done_count = 0
    t0 = time.perf_counter()

    # A backstop independent of the per-chunk token cap: bounds the whole job's spend
    # relative to what it was actually estimated at, not just each individual request.
    preflight = estimate_translation(chunks, spec)
    cost_ceiling = max(preflight.cost.usd * COST_CEILING_MULTIPLIER, MIN_COST_CEILING_USD)

    pool = ThreadPoolExecutor(max_workers=spec.max_parallel)
    first_error: BaseException | None = None
    try:
        futures = {
            pool.submit(_translate_one, i, chunk, client, spec): i for i, chunk in enumerate(chunks)
        }
        for future in as_completed(futures):
            try:
                idx, translated, chunk_input_tokens, chunk_output_tokens = future.result()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
                    # Chunks not yet started are cancellable; every one cancelled here
                    # is a request we do not pay for.
                    for pending in futures:
                        pending.cancel()
                continue
            results[idx] = translated
            input_tokens += chunk_input_tokens
            output_tokens += chunk_output_tokens
            done_count += 1
            if on_progress:
                on_progress(done_count, total)
            if first_error is None and cost_usd(spec, input_tokens, output_tokens) > cost_ceiling:
                first_error = RuntimeError(
                    f"Translation cost exceeded its ${cost_ceiling:.2f} ceiling after "
                    f"{done_count}/{total} chapters — aborting the rest."
                )
                for pending in futures:
                    pending.cancel()
    finally:
        pool.shutdown(wait=True, cancel_futures=True)

    if first_error is not None:
        log.warning(
            "translate_chunks: aborted after %d/%d chapters (%d in + %d out tokens billed)",
            done_count,
            total,
            input_tokens,
            output_tokens,
        )
        raise first_error

    return TranslateResult(
        chunks=[part for part in results if part is not None],
        duration_s=round(time.perf_counter() - t0, 3),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=CostLine(COST_LABEL, cost_usd(spec, input_tokens, output_tokens)),
    )
