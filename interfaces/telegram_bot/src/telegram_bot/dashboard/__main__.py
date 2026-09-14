"""Entrypoint for the usage dashboard (localhost only by design)."""

from __future__ import annotations

import argparse

import uvicorn

from shared.config import settings
from shared.obs import get_logger

from ..tracing import init_tracing
from .app import create_app

log = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="ai_agents usage dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()

    init_tracing(settings=settings, service_name="ai-agents-usage-dashboard")
    log.info("usage dashboard on %s:%s (db=%s)", args.host, args.port, settings.telegram_db_path)
    uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
