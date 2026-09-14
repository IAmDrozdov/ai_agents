"""Parse PDF, DOCX or plain/markdown bytes into text and chapters."""

from __future__ import annotations

import hashlib
import io
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import PurePosixPath

from shared.doc.chapters import split_into_chapters
from shared.obs import get_logger

log = get_logger(__name__)

_TEXT_EXTENSIONS = {".md", ".markdown", ".txt"}
_DOCX_EXTENSIONS = {".docx"}
_DOCX_HEADING_STYLES = ("Heading 1", "Heading 2")
_EMPTY_TEXT_ERRORS = {
    "markdown": "document produced no extractable text",
    "docx": "DOCX produced no extractable text",
    "pdf": "PDF produced no extractable text",
}
_MEMO_SIZE = 4


class DocumentError(ValueError):
    """The document cannot be used: empty, unreadable, or over the size backstop."""


@dataclass(frozen=True)
class ParsedDocument:
    text: str
    chapters: list[str]

    @property
    def char_count(self) -> int:
        return len(self.text)


_memo: OrderedDict[tuple[str, int, int], ParsedDocument] = OrderedDict()
_memo_lock = threading.Lock()


def _is_text_filename(filename: str) -> bool:
    return PurePosixPath(filename.lower()).suffix in _TEXT_EXTENSIONS


def _is_docx_filename(filename: str) -> bool:
    return PurePosixPath(filename.lower()).suffix in _DOCX_EXTENSIONS


def _extract_docx_chapters(file_bytes: bytes, target_chars: int) -> tuple[str, list[str]]:
    import docx

    document = docx.Document(io.BytesIO(file_bytes))
    lines: list[str] = []
    heading_indexes: list[int] = []
    for para in document.paragraphs:
        para_text = para.text.strip()
        if not para_text:
            continue
        try:
            style_name = para.style.name or "" if para.style else ""
        except Exception:
            style_name = ""
        if style_name.startswith(_DOCX_HEADING_STYLES) or style_name == "Title":
            heading_indexes.append(len(lines))
        lines.append(para_text)

    text = "\n".join(lines).strip()
    if not text:
        return "", []

    if len(heading_indexes) >= 2:
        starts = heading_indexes if heading_indexes[0] == 0 else [0, *heading_indexes]
        chapters: list[str] = []
        for idx, start in enumerate(starts):
            end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
            chapter_text = "\n".join(lines[start:end]).strip()
            if chapter_text:
                chapters.append(chapter_text)
        if chapters:
            return text, chapters

    return text, split_into_chapters(text, target_chars)


def _extract_pdf_chapters(file_bytes: bytes, target_chars: int) -> tuple[str, list[str]]:
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    pages = [page.extract_text() or "" for page in reader.pages]
    text = "\n".join(pages).strip()
    if not text:
        return "", []

    try:
        outline = reader.outline
        if outline:
            page_starts: list[int] = []
            for item in outline:
                if isinstance(item, list):
                    continue
                page_num = reader.get_destination_page_number(item)
                if page_num is not None and page_num not in page_starts:
                    page_starts.append(page_num)
            page_starts = sorted(set(page_starts))
            if len(page_starts) >= 2:
                chapters: list[str] = []
                for idx, start in enumerate(page_starts):
                    end = page_starts[idx + 1] if idx + 1 < len(page_starts) else len(pages)
                    chapter_text = "\n".join(pages[start:end]).strip()
                    if chapter_text:
                        chapters.append(chapter_text)
                if chapters:
                    return text, chapters
    except Exception:
        log.exception("parse_document: outline chapter split failed, falling back")

    return text, split_into_chapters(text, target_chars)


def _parse(file_bytes: bytes, filename: str, chapter_char_target: int) -> tuple[str, list[str]]:
    if _is_text_filename(filename):
        kind = "markdown"
        text = file_bytes.decode("utf-8", errors="replace").strip()
        chapters = split_into_chapters(text, chapter_char_target) if text else []
    elif _is_docx_filename(filename):
        kind = "docx"
        text, chapters = _extract_docx_chapters(file_bytes, chapter_char_target)
    else:
        kind = "pdf"
        text, chapters = _extract_pdf_chapters(file_bytes, chapter_char_target)
    if not text:
        raise DocumentError(_EMPTY_TEXT_ERRORS[kind])
    log.info(
        "parse_document: %s %s, %d chars, %d chapters", kind, filename, len(text), len(chapters)
    )
    return text, chapters


def parse_document(
    file_bytes: bytes,
    filename: str,
    *,
    chapter_char_target: int,
    max_document_chars: int,
) -> ParsedDocument:
    """Text + chapters for a document; repeated calls with the same bytes and knobs are free."""
    if not file_bytes:
        raise DocumentError("the file is empty")
    key = (hashlib.sha256(file_bytes).hexdigest(), chapter_char_target, max_document_chars)
    with _memo_lock:
        cached = _memo.get(key)
        if cached is not None:
            _memo.move_to_end(key)
            return cached

    try:
        text, chapters = _parse(file_bytes, filename, chapter_char_target)
    except DocumentError:
        raise
    except Exception as exc:
        log.exception("parse_document failed")
        raise DocumentError(str(exc)) from exc
    if len(text) > max_document_chars:
        raise DocumentError(
            f"document is {len(text):,} characters, over the "
            f"{max_document_chars:,} limit — split it into smaller files"
        )

    parsed = ParsedDocument(text=text, chapters=chapters)
    with _memo_lock:
        _memo[key] = parsed
        while len(_memo) > _MEMO_SIZE:
            _memo.popitem(last=False)
    return parsed
