# Build context: repo root (see docker-compose.yml). One image serves both
# the bot and the Mini App; the service picks its entrypoint via `command`.
FROM python:3.12-slim

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"
WORKDIR /app

# Untrusted documents are parsed in this container, so the process is not root.
# /data exists in the image so a fresh named volume inherits this ownership.
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data \
    && chown app:app /data

# Manifests first: third-party deps reinstall only when uv.lock changes, so a
# code-only deploy skips reinstalling them on the droplet's single vCPU.
COPY pyproject.toml uv.lock ./
COPY shared/pyproject.toml shared/
COPY workflows/doc_translator/pyproject.toml workflows/doc_translator/
COPY workflows/pdf_tts/pyproject.toml workflows/pdf_tts/
COPY workflows/yt_dub/pyproject.toml workflows/yt_dub/
COPY apps/notes/pyproject.toml apps/notes/
COPY interfaces/smoke/pyproject.toml interfaces/smoke/
COPY interfaces/telegram_bot/pyproject.toml interfaces/telegram_bot/
# uv and its download cache are mounted for the build only; neither lands in the image.
RUN --mount=from=ghcr.io/astral-sh/uv:0.11,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-packages --no-install-workspace

COPY . .
RUN --mount=from=ghcr.io/astral-sh/uv:0.11,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-packages

USER app
CMD ["telegram-bot"]
