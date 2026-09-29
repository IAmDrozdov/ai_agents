"""A deterministic, offline Classifier for tests and dry runs."""

from __future__ import annotations

from notes.classify.port import Filing, FilingRequest

GIST_LIMIT = 200


class FakeClassifier:
    async def file(self, request: FilingRequest) -> Filing:
        text = request.caption or request.annotation or request.title or request.url or ""
        gist = " ".join(text.split())[:GIST_LIMIT]
        return Filing(sections=[], gist=gist, title=request.title, author=request.author)
