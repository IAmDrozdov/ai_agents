"""Entrypoint for the notes web UI (localhost only by design)."""

from __future__ import annotations

import argparse

import uvicorn

from notes.db import Database
from shared.config import settings
from shared.obs import get_logger

from .app import create_app

log = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="notes web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8082)
    args = parser.parse_args()

    db = Database(settings.notes_db_path)
    db.init()
    log.info("notes web UI on %s:%s (db=%s)", args.host, args.port, settings.notes_db_path)
    uvicorn.run(create_app(db), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
