"""OpenTelemetry bootstrap for the Telegram interface."""

from __future__ import annotations

from shared.config import Settings
from shared.obs import get_logger
from shared.obs.tracing import init_tracing_provider, service_version

log = get_logger(__name__)


def init_tracing(settings: Settings, service_name: str = "maxi-bot-telegram") -> None:
    """Initialize the global tracer provider when OTEL is enabled."""
    if not settings.otel_enabled:
        log.info("OpenTelemetry disabled for %s", service_name)
        return

    init_tracing_provider(
        settings=settings,
        service_name=service_name,
        version_str=service_version("telegram-bot-interface"),
    )
    log.info("OpenTelemetry initialized for %s", service_name)
