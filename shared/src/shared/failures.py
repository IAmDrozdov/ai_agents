"""Turn a failed job's exception into a verdict: whose side, what happened, what to do.

Provider-side verdicts are verified with a live probe; see interfaces/telegram_bot/README.md
"Failure messages". Lives in `shared/` because interfaces may not import the OpenAI SDK (ADR-005).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Literal

from .config import Settings
from .obs import get_logger

log = get_logger(__name__)

# "provider" — upstream is broken; waiting is the fix.
# "config"   — our keys/model ids/env are wrong; needs a human.
# "input"    — this particular document or request is the problem.
# "internal" — our code broke; needs a human.
Scope = Literal["provider", "config", "input", "internal"]

_STATUS_URL = "https://status.openai.com/api/v2/summary.json"
_STATUS_TIMEOUT_S = 6.0
_PROBE_TIMEOUT_S = 8.0


@dataclass(frozen=True)
class ProviderHealth:
    """Result of looking at the provider right now, after a failure."""

    reachable: bool | None = None  # None: not probed
    indicator: str | None = None  # status page severity: none/minor/major/critical
    incident: str | None = None  # active incident title, if any

    def summary(self) -> str:
        bits = []
        if self.reachable is True:
            bits.append("their API answers now, so the error looks transient")
        elif self.reachable is False:
            bits.append("their API is not answering us right now")
        if self.incident:
            severity = f" ({self.indicator})" if self.indicator else ""
            bits.append(f"status page: {self.incident}{severity}")
        elif self.indicator and self.indicator != "none":
            bits.append(f"status page: {self.indicator} degradation")
        return "; ".join(bits)


@dataclass(frozen=True)
class Failure:
    scope: Scope
    headline: str
    detail: str
    action: str
    health: ProviderHealth | None = None

    @property
    def verdict(self) -> str:
        """The one line worth reading: does this clear itself, or does it need a human?"""
        if self.scope == "provider":
            return "Wait and retry — nothing to fix on our side."
        if self.scope == "input":
            return "Try another document — waiting will not help."
        return "Needs a fix — waiting will not help."


def _status_page() -> tuple[str | None, str | None]:
    """(indicator, incident_title) from the provider's status page. Best effort."""
    try:
        request = urllib.request.Request(_STATUS_URL, headers={"User-Agent": "ai-agents-bot/1.0"})
        with urllib.request.urlopen(request, timeout=_STATUS_TIMEOUT_S) as response:
            data: dict[str, Any] = json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        log.warning("status page unreachable: %s", exc)
        return None, None
    status = data.get("status") or {}
    incidents = data.get("incidents") or []
    title = incidents[0].get("name") if incidents else None
    return status.get("indicator"), title


def _probe_openai(settings: Settings) -> bool | None:
    """Cheap unbilled GET against the API. True/False reachable, None if no key."""
    if not settings.openai_api_key:
        return None
    try:
        import openai

        client = openai.OpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=_PROBE_TIMEOUT_S,
            max_retries=0,
        )
        client.models.list()
        return True
    except Exception as exc:  # noqa: BLE001 - any failure means "not reachable"
        log.warning("openai probe failed: %s", type(exc).__name__)
        return False


def check_openai(settings: Settings) -> ProviderHealth:
    """Blocking: is OpenAI actually broken right now, or was it just this request?"""
    reachable = _probe_openai(settings)
    indicator, incident = _status_page()
    health = ProviderHealth(reachable=reachable, indicator=indicator, incident=incident)
    log.info("openai health: %s", health)
    return health


def _from_status_code(code: int, message: str, api_code: str | None) -> Failure:
    if code == 429:
        # Quota exhaustion wears the same status code as ordinary throttling, but
        # only one of them clears itself by waiting.
        if api_code == "insufficient_quota":
            return Failure(
                "config",
                "OpenAI quota exhausted",
                "HTTP 429 (insufficient_quota).",
                "Top up or raise the limit on the OpenAI account.",
            )
        return Failure(
            "provider",
            "Rate limited by OpenAI",
            "HTTP 429.",
            "If it keeps happening, lower max_parallel.",
        )
    if code >= 500:
        return Failure(
            "provider",
            "OpenAI server error",
            f"HTTP {code}. The request was accepted but their side failed to process it.",
            "Their API recovers on its own.",
        )
    if code in (401, 403):
        return Failure(
            "config",
            "OpenAI rejected our credentials",
            f"HTTP {code}.",
            "Check OPENAI_API_KEY in the droplet's .env, then redeploy.",
        )
    if code == 404:
        return Failure(
            "config",
            "Model or endpoint not found",
            f"HTTP 404. {message}",
            "A configured model id is probably wrong or no longer available.",
        )
    if code in (400, 422):
        return Failure(
            "input",
            "OpenAI rejected the request",
            f"HTTP {code}. {message}",
            "The message above says whether it is the document or a config value.",
        )
    return Failure(
        "internal",
        "Unexpected OpenAI response",
        f"HTTP {code}. {message}",
        "Needs a look at the logs.",
    )


def classify(exc: BaseException) -> Failure:
    """Turn an exception into a verdict. Pure — no network, safe to call anywhere."""
    try:
        import openai
    except ImportError:  # pragma: no cover - openai is a hard dependency of shared
        return Failure("internal", "Job failed", str(exc), "Needs a look at the logs.")

    if isinstance(exc, openai.APIStatusError):
        # Read the error object out of the body ourselves. `exc.code` is populated
        # from the TOP level of the response, but OpenAI nests code/message under
        # "error", so the SDK's own attribute is always None here.
        message, api_code = "", None
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                message = str(error.get("message") or "")
                api_code = error.get("code")
        return _from_status_code(exc.status_code, message[:300], api_code)

    if isinstance(exc, openai.APITimeoutError):
        return Failure(
            "provider",
            "OpenAI timed out",
            "No response arrived before the timeout.",
            "Usually load on their side.",
        )
    if isinstance(exc, openai.APIConnectionError):
        return Failure(
            "provider",
            "Cannot reach OpenAI",
            "The connection failed before any response arrived.",
            "If it persists, check the droplet's network.",
        )

    return Failure(
        "internal",
        "Job failed",
        f"{type(exc).__name__}: {exc}"[:300],
        "This one is on us — check the logs.",
    )


def diagnose(exc: BaseException, settings: Settings) -> Failure:
    """Blocking: classify `exc`, and for provider-side verdicts go and verify it.

    The probe is what makes the answer trustworthy: it separates "they are down"
    from "they were down for that one request and are fine now".
    """
    failure = classify(exc)
    if failure.scope != "provider":
        return failure
    health = check_openai(settings)
    action = failure.action
    if health.reachable is True:
        action = "Their API responds again, so this was a passing blip."
    return Failure(failure.scope, failure.headline, failure.detail, action, health)


def from_message(message: str) -> Failure:
    """Verdict for a workflow-reported error string (no exception to inspect)."""
    return Failure(
        "input",
        "Could not process the document",
        message[:300],
        "Check the file. If it looks fine, this is a bug on our side.",
    )
