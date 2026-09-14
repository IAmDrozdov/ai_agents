"""Chapter splitting for long documents."""

from __future__ import annotations

import re

_HEADING_PATTERN = re.compile(
    r"^(?:#{1,6}\s+\S|(?:chapter|глава)\b.*|\d+\.\s+\S)",
    re.MULTILINE | re.IGNORECASE,
)

# A numbered list (e.g. every line starting "1. ", "2. ") matches the heading pattern
# once per line, so an adversarial or just very long list could turn one document into
# hundreds of thousands of "chapters" — one completion request each. Above this count,
# fall back to size-based chunking instead.
MAX_CHAPTERS = 2000


def _split_by_size(text: str, target_chars: int) -> list[str]:
    chunks: list[str] = []
    remaining = text.strip()
    while remaining:
        if len(remaining) <= target_chars:
            chunks.append(remaining)
            break
        split_at = remaining.rfind(" ", 0, target_chars)
        if split_at == -1:
            split_at = target_chars
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip()
    return chunks


def split_into_chapters(text: str, target_chars: int = 8000) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []

    matches = list(_HEADING_PATTERN.finditer(stripped))
    if 2 <= len(matches) <= MAX_CHAPTERS:
        chapters: list[str] = []
        for idx, match in enumerate(matches):
            start = match.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(stripped)
            chapter = stripped[start:end].strip()
            if chapter:
                chapters.append(chapter)
        if chapters:
            return chapters

    size_chunks = _split_by_size(stripped, target_chars)
    return size_chunks if size_chunks else [stripped]
