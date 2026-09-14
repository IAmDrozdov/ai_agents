# Build context: repo root (see docker-compose.yml). One image serves both
# the bot and the dashboard; the service picks its entrypoint via `command`.
FROM python:3.12.8-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# Manifests first: third-party deps reinstall only when uv.lock changes, so a
# code-only deploy skips reinstalling them on the droplet's single vCPU.
COPY pyproject.toml uv.lock ./
COPY shared/pyproject.toml shared/
COPY workflows/doc_translator/pyproject.toml workflows/doc_translator/
COPY workflows/pdf_tts/pyproject.toml workflows/pdf_tts/
COPY workflows/yt_dub/pyproject.toml workflows/yt_dub/
COPY interfaces/smoke/pyproject.toml interfaces/smoke/
COPY interfaces/telegram_bot/pyproject.toml interfaces/telegram_bot/
RUN uv sync --frozen --no-dev --all-packages --no-install-workspace

COPY . .
RUN uv sync --frozen --no-dev --all-packages

ENV PATH="/app/.venv/bin:$PATH"

# Untrusted documents are parsed in this container, so the process is not root.
# /data exists in the image so a fresh named volume inherits this ownership.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data \
    && chown -R app:app /app /data
USER app

CMD ["telegram-bot"]
