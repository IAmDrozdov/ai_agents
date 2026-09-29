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


AUTHOR_MAX_CHARS = 60
AUTHOR_MAX_WORDS = 6


def _clean(value: object) -> str | None:
    text = str(value).strip() if value else ""
    return text or None


def _clean_author(value: object) -> str | None:
    """Free-form bylines (telegra.ph) can hold a whole sentence; that is not a name."""
    text = _clean(value)
    if text is None or len(text) > AUTHOR_MAX_CHARS or len(text.split()) > AUTHOR_MAX_WORDS:
        return None
    return text


def page_metadata(html: str) -> PageMeta:
    """Blocking (trafilatura); call it in a thread."""
    import trafilatura

    meta = trafilatura.extract_metadata(html)
    if meta is None:
        return PageMeta()
    return PageMeta(
        title=_clean(meta.title),
        author=_clean_author(meta.author),
        description=_clean(meta.description),
        image=_clean(meta.image),
        sitename=_clean(meta.sitename),
    )
