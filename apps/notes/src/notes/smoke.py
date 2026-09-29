"""`uv run notes-smoke <url-or-text>`: fetch and file one input, print what came back (ADR-001)."""

from __future__ import annotations

import argparse
import asyncio

from notes.classify import make_classifier
from notes.classify.port import FilingRequest, SectionBrief
from notes.domain.sections import STARTER_SECTIONS
from notes.domain.urls import extract_urls
from notes.enrich.http import AiohttpClient, FetchError
from notes.enrich.providers import Fetched, fetch_for
from shared.config import settings


async def _smoke(text: str) -> int:
    extracted = extract_urls(text)
    url = extracted.urls[0] if extracted.urls else None
    fetched: Fetched | None = None
    if url:
        try:
            fetched = await fetch_for(url, AiohttpClient())
        except FetchError as exc:
            print(f"fetch failed: {exc.__class__.__name__}: {exc}")
            return 1
        for field in ("source", "title", "author", "image_url", "caption"):
            print(f"{field:>9}: {getattr(fetched, field)}")
    request = FilingRequest(
        kind="link" if url else "note",
        url=url,
        source=fetched.source if fetched else None,
        title=fetched.title if fetched else None,
        author=fetched.author if fetched else None,
        caption=fetched.caption if fetched else None,
        annotation=extracted.annotation,
        sections=[SectionBrief(slug=s[0], name=s[1], hint=s[4]) for s in STARTER_SECTIONS],
    )
    filing = await make_classifier(settings).file(request)
    print(f"   filing: {filing.sections or ['other']} ({settings.notes_classifier_provider})")
    print(f"     gist: {filing.gist}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="notes-smoke", description=__doc__)
    parser.add_argument("text", help="a link, or plain text for a Note")
    raise SystemExit(asyncio.run(_smoke(parser.parse_args().text)))


if __name__ == "__main__":
    main()
