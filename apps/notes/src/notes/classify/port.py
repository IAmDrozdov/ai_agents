"""What a Classifier is asked and what it answers, independent of any provider."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

CAPTION_LIMIT = 2000


class SectionBrief(BaseModel):
    slug: str
    name: str
    hint: str


class FilingRequest(BaseModel):
    kind: Literal["link", "note"]
    url: str | None = None
    source: str | None = None
    title: str | None = None
    author: str | None = None
    caption: str | None = None
    annotation: str = ""
    sections: list[SectionBrief]

    def clipped_caption(self) -> str | None:
        if self.caption is None:
            return None
        return self.caption[:CAPTION_LIMIT]


class Filing(BaseModel):
    sections: list[str] = Field(default_factory=list)
    gist: str = ""
    title: str | None = None
    author: str | None = None
    source: str | None = None


class ClassifierError(Exception):
    """Base for everything a Classifier can fail with."""


class ClassifierUnavailable(ClassifierError):
    """Transient: rate limit, outage, network. Worth retrying later."""


class ClassifierRejected(ClassifierError):
    """Permanent for this deployment: bad key, bad request, wrong model. No retry."""


class ClassifierRefused(ClassifierError):
    """The provider declined this content. The Item is filed to Other and left alone."""


class Classifier(Protocol):
    async def file(self, request: FilingRequest) -> Filing: ...
