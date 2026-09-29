"""Entrypoint for the admin Mini App server (published by the funnel sidecar, ADR-016)."""

from __future__ import annotations

import argparse
import sys

import uvicorn

from notes.db import Database
from shared.config import settings
from shared.obs import get_logger

from ..tracing import init_tracing
from .app import create_app

log = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="admin Mini App server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8083)
    args = parser.parse_args()

    if settings.admin_telegram_id is None:
        log.error("ADMIN_TELEGRAM_ID is not set — refusing to start")
        sys.exit(1)
    init_tracing(settings=settings, service_name="ai-agents-miniapp")
    notes_db = Database(settings.notes_db_path)
    notes_db.init()
    log.info("mini app on %s:%s (notes=%s)", args.host, args.port, settings.notes_db_path)
    uvicorn.run(create_app(notes_db), host=args.host, port=args.port, server_header=False)


if __name__ == "__main__":
    main()
