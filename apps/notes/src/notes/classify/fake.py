"""A deterministic, offline Classifier for tests and dry runs."""

from __future__ import annotations

import re
from datetime import datetime

from notes.classify.port import DueRequest, Filing, FilingRequest

GIST_LIMIT = 200
# «напомни 2026-10-10 19:00»: the offline stand-in for the model reading a Due.
REMIND = re.compile(r"напомни\s+(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})", re.IGNORECASE)


class FakeClassifier:
    async def file(self, request: FilingRequest) -> Filing:
        text = (
            request.caption
            or request.annotation
            or request.transcript
            or request.title
            or request.url
            or ""
        )
        gist = " ".join(text.split())[:GIST_LIMIT]
        return Filing(
            sections=[], gist=gist, title=request.title, author=request.author, due=_due(request)
        )

    async def due(self, request: DueRequest) -> datetime | None:
        return _find(request.text)


def _due(request: FilingRequest) -> datetime | None:
    for words in (request.annotation, request.transcript):
        if due := _find(words or ""):
            return due
    return None


def _find(words: str) -> datetime | None:
    if match := REMIND.search(words):
        return datetime.strptime(" ".join(match.groups()), "%Y-%m-%d %H:%M")
    return None
