"""Logging helpers. Use get_logger(__name__) instead of print()."""

from __future__ import annotations

import logging

from shared.config import settings


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(settings.log_level)
    return logger


__all__ = ["get_logger"]
