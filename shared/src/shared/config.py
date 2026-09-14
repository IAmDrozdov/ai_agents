"""Layer 1 config: env-driven Settings. See ADR-004."""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Infrastructure config. Secrets, hosts, log level, operator policy. NO workflow knobs."""

    openai_api_key: SecretStr | None = None

    telegram_bot_token: SecretStr | None = None
    admin_telegram_id: int | None = None
    telegram_db_path: str = "data/telegram_bot.sqlite3"

    # Telegram bot operator policy, per deployment (ADR-004, amended 2026-09-13).
    bot_languages: str = "English,Russian,Chinese,Japanese,Korean,French,German,Spanish"
    bot_default_source_language: str = "English"
    bot_default_target_language: str = "Russian"
    bot_max_job_cost_usd: float = 10.0
    bot_daily_user_cost_limit_usd: float = 25.0

    log_level: str = "INFO"
    otel_enabled: bool = False
    otel_service_namespace: str = "ai_agents"
    otel_deployment_environment: str = "local"
    otel_exporter_otlp_endpoint: str = "http://localhost:8200"
    otel_exporter_otlp_headers: str | None = None
    otel_traces_sampler: str = "always_on"
    otel_traces_sampler_arg: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
