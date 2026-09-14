"""The workflow job contract: what every interface needs to preview, price, run and deliver."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal, Protocol

from shared.config import Settings

SourceKind = Literal["document", "link"]


@dataclass(frozen=True)
class DocumentSource:
    file_bytes: bytes
    filename: str

    kind: SourceKind = field(default="document", init=False)


@dataclass(frozen=True)
class LinkSource:
    url: str

    kind: SourceKind = field(default="link", init=False)


Source = DocumentSource | LinkSource


@dataclass(frozen=True)
class Preview:
    """Free, unbilled look at a source. `payload` is workflow-private; interfaces pass it back untouched."""

    title: str
    char_count: int
    chapter_count: int
    duration_s: float | None = None
    note: str | None = None
    error: str | None = None
    payload: Mapping[str, object] = field(default_factory=dict)

    @classmethod
    def failed(cls, title: str, error: str) -> Preview:
        return cls(title=title, char_count=0, chapter_count=0, error=error)


@dataclass(frozen=True)
class CostLine:
    label: str
    usd: float


@dataclass(frozen=True)
class Cost:
    total_usd: float
    lines: tuple[CostLine, ...] = ()

    @classmethod
    def of(cls, *lines: CostLine) -> Cost:
        return cls(total_usd=round(sum(line.usd for line in lines), 6), lines=tuple(lines))


@dataclass(frozen=True)
class Estimate:
    cost: Cost
    approximate: bool = False
    error: str | None = None

    @classmethod
    def failed(cls, error: str) -> Estimate:
        return cls(cost=Cost.of(), error=error)


@dataclass(frozen=True)
class FileDeliverable:
    data: bytes
    filename: str


@dataclass(frozen=True)
class AudioDeliverable:
    data: bytes
    filename: str
    # Per-chunk Ogg/Opus blobs, only when the caller may need to split; else empty.
    parts: list[bytes]
    # Playable length; 0.0 when unknown.
    duration_s: float


Deliverable = FileDeliverable | AudioDeliverable


@dataclass(frozen=True)
class Fact:
    label: str
    value: str


@dataclass(frozen=True)
class Result:
    deliverable: Deliverable | None
    cost: Cost
    facts: tuple[Fact, ...] = ()
    error: str | None = None

    @classmethod
    def failed(cls, error: str, cost: Cost | None = None) -> Result:
        return cls(deliverable=None, cost=cost or Cost.of(), error=error)


class Progress(Protocol):
    def phase(self, name: str, total: int) -> None: ...

    def tick(self, done: int, total: int) -> None: ...


class NoProgress:
    def phase(self, name: str, total: int) -> None:
        return None

    def tick(self, done: int, total: int) -> None:
        return None


NO_PROGRESS: Progress = NoProgress()


@dataclass(frozen=True)
class Workflow[ConfigT]:
    """A workflow package's descriptor; interfaces hold a list of these and nothing else per workflow."""

    id: str
    config_type: type[ConfigT]
    accepts: frozenset[SourceKind]
    preview: Callable[[Settings, ConfigT, Source], Preview]
    estimate: Callable[[Settings, ConfigT, Preview], Estimate]
    run: Callable[[Settings, ConfigT, Preview, Progress], Result]
    # Stable key for speed statistics: same key = comparable seconds-per-char.
    speed_profile: Callable[[ConfigT], str]
