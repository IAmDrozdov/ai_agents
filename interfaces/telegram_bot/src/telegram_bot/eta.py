"""History-backed duration predictor for pending-job ETA labels.

Learns ``seconds / char`` rates from the bot's own ``jobs`` table. Cache is an
LRU with no TTL; entries rebuild every ``REBUILD_EVERY`` finished jobs.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from . import db
from .registry import REGISTRY, by_id

REBUILD_EVERY = 4
SAMPLE_LIMIT = 30
MIN_SAMPLES = 3
CACHE_SIZE = 32

# Cold-start prior (sec/char). Tuned from droplet history; self-corrects after ~3 jobs.
_PRIOR = 0.0035
_PRIORS: dict[str, float] = {entry.id: _PRIOR for entry in REGISTRY}


@dataclass(frozen=True)
class _CacheEntry:
    rate: float
    generation: int


_generation = 0
_cache: OrderedDict[str, _CacheEntry] = OrderedDict()


def note_job_finished() -> None:
    """Bump the generation counter so stale rates rebuild after a few jobs."""
    global _generation
    _generation += 1


def format_eta(seconds: float | None) -> str:
    if seconds is None or seconds <= 0:
        return ""
    total = max(1, int(round(seconds)))
    if total < 60:
        return f"~{total}s"
    minutes = total // 60
    rem = total % 60
    if minutes < 60:
        return f"~{minutes} min" if rem < 15 else f"~{minutes} min {rem}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"~{hours} h" if mins == 0 else f"~{hours} h {mins} min"


def profile_key(workflow_id: str, config: Any) -> str:
    """Stable key so a slow model does not poison a fast one's rate."""
    entry = by_id(workflow_id)
    if entry is None:
        return f"{workflow_id}|unknown"
    if not isinstance(config, BaseModel):
        try:
            config = entry.workflow.config_type.model_validate(_as_dict(config))
        except ValidationError:
            # Rows written before the config shape changed still feed the per-workflow rate.
            return f"{workflow_id}|unknown"
    return entry.workflow.speed_profile(config)


def predict_seconds(workflow_id: str, config: Any, char_count: int) -> float | None:
    if char_count <= 0:
        return None
    key = profile_key(workflow_id, config)
    rate = _rate_for(key, workflow_id)
    return rate * char_count


def _rate_for(key: str, workflow_id: str) -> float:
    entry = _cache.get(key)
    if entry is not None and _generation - entry.generation < REBUILD_EVERY:
        _cache.move_to_end(key)
        return entry.rate

    rate = _compute_rate(key, workflow_id)
    _cache[key] = _CacheEntry(rate=rate, generation=_generation)
    _cache.move_to_end(key)
    while len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)
    return rate


def _compute_rate(key: str, workflow_id: str) -> float:
    samples = db.recent_job_samples(workflow_id, limit=SAMPLE_LIMIT)
    exact = [s for s in samples if profile_key(workflow_id, s.get("config_json") or {}) == key]
    rate = _median_rate(exact)
    if rate is not None:
        return rate
    agent_rate = _median_rate(samples)
    if agent_rate is not None:
        return agent_rate
    return _PRIORS.get(workflow_id, _PRIOR)


def _median_rate(samples: list[dict[str, Any]]) -> float | None:
    rates: list[float] = []
    for sample in samples:
        chars = sample.get("char_count")
        duration = sample.get("duration_s")
        if not chars or not duration:
            continue
        try:
            c = int(chars)
            d = float(duration)
        except (TypeError, ValueError):
            continue
        if c > 0 and d > 0:
            rates.append(d / c)
    if len(rates) < MIN_SAMPLES:
        return None
    rates.sort()
    mid = len(rates) // 2
    if len(rates) % 2:
        return rates[mid]
    return (rates[mid - 1] + rates[mid]) / 2


def _as_dict(config: Any) -> dict[str, Any]:
    if config is None:
        return {}
    if isinstance(config, dict):
        return config
    if isinstance(config, str):
        try:
            parsed = json.loads(config)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}
    return {}
