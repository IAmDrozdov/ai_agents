"""Page metadata (title, author, description, image, site) out of raw HTML."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageMeta:
    title: str | None = None
    author: str | None = None
    description: str | None = None
    image: str | None = None
    sitename: str | None = None


def _clean(value: object) -> str | None:
    text = str(value).strip() if value else ""
    return text or None


def page_metadata(html: str) -> PageMeta:
    """Blocking (trafilatura); call it in a thread."""
    import trafilatura

    meta = trafilatura.extract_metadata(html)
    if meta is None:
        return PageMeta()
    return PageMeta(
        title=_clean(meta.title),
        author=_clean(meta.author),
        description=_clean(meta.description),
        image=_clean(meta.image),
        sitename=_clean(meta.sitename),
    )
