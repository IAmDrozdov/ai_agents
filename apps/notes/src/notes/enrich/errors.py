"""Errors shared by the fetch side of Enrichment."""

from __future__ import annotations


class FetchError(Exception):
    """The page or endpoint could not be fetched or read."""
