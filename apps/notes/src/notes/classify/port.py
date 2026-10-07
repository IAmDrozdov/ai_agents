"""What a Classifier is asked and what it answers, independent of any provider."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field

CAPTION_LIMIT = 2000
TRANSCRIPT_LIMIT = 3000
# A Voice's Transcript is the whole Item, so the Classifier sees far more of it.
VOICE_TRANSCRIPT_LIMIT = 12000


class SectionBrief(BaseModel):
    slug: str
    name: str
    hint: str


class FilingRequest(BaseModel):
    kind: Literal["link", "note", "file", "voice"]
    url: str | None = None
    file_name: str | None = None
    source: str | None = None
    title: str | None = None
    author: str | None = None
    caption: str | None = None
    annotation: str = ""
    sender: str | None = None
    transcript: str | None = None
    image: bytes | None = Field(default=None, exclude=True)
    image_mime: str | None = Field(default=None, exclude=True)
    now_local: str | None = None  # the Capture moment in the Owner's zone, with the weekday
    zone: str = "UTC"
    sections: list[SectionBrief]

    def clipped_caption(self) -> str | None:
        if self.caption is None:
            return None
        return self.caption[:CAPTION_LIMIT]

    def clipped_transcript(self) -> str | None:
        limit = VOICE_TRANSCRIPT_LIMIT if self.kind == "voice" else TRANSCRIPT_LIMIT
        return self.transcript[:limit] if self.transcript else None


class Filing(BaseModel):
    sections: list[str] = Field(default_factory=list)
    gist: str = ""
    title: str | None = None
    author: str | None = None
    source: str | None = None
    confident: bool = True
    due: datetime | None = None  # a naive wall-clock moment in the Owner's zone (ADR-0011)


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
