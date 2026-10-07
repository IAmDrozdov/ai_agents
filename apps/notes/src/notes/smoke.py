"""`uv run notes-smoke <url-or-text | --voice FILE>`: file one input, print what came back (ADR-001)."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path

from notes.classify import make_classifier
from notes.classify.port import FilingRequest, SectionBrief
from notes.domain import items
from notes.domain.sections import STARTER_SECTIONS
from notes.domain.urls import extract_urls
from notes.enrich.http import AiohttpClient, FetchError
from notes.enrich.pipeline import file_with_fallback, load_image
from notes.enrich.providers import Fetched, fetch_for
from shared.audio import SttSpec, transcribe
from shared.config import settings

TRANSCRIPT_HEAD = 400


def _clock(now: str | None, zone: str) -> str:
    """The Capture moment the Classifier is told: --now, or the current time, in `zone`."""
    moment = datetime.strptime(now, "%Y-%m-%d %H:%M") if now else datetime.now(items.zone(zone))
    return f"{moment:%Y-%m-%d %H:%M}, {items.WEEKDAYS_RU[moment.weekday()]}"


async def _smoke(text: str, now: str | None, zone: str) -> int:
    extracted = extract_urls(text)
    # One URL is a Link; none or several is a Note of the whole text (ADR-0009).
    url = extracted.urls[0] if len(extracted.urls) == 1 else None
    http = AiohttpClient()
    fetched: Fetched | None = None
    if url:
        try:
            fetched = await fetch_for(url, http)
        except FetchError as exc:
            print(f"fetch failed: {exc.__class__.__name__}: {exc}")
            return 1
        for field in ("source", "title", "author", "image_url", "caption"):
            print(f"{field:>9}: {getattr(fetched, field)}")
    image = await load_image(http, fetched.image_url) if fetched else None
    request = FilingRequest(
        kind="link" if url else "note",
        url=url,
        image=image[0] if image else None,
        image_mime=image[1] if image else None,
        source=fetched.source if fetched else None,
        title=fetched.title if fetched else None,
        author=fetched.author if fetched else None,
        caption=fetched.caption if fetched else None,
        annotation=extracted.annotation if url else text,
        now_local=_clock(now, zone),
        zone=zone,
        sections=[SectionBrief(slug=s[0], name=s[1], hint=s[4]) for s in STARTER_SECTIONS],
    )
    return await _file(request, http, image is not None)


async def _smoke_voice(path: Path, now: str | None, zone: str) -> int:
    """Transcribe a local voice file the way Enrichment does, then file it as a Voice."""
    result = await asyncio.to_thread(
        transcribe, settings, path.read_bytes(), SttSpec(), duration_s=0, filename=path.name
    )
    head = result.text[:TRANSCRIPT_HEAD] + ("…" if len(result.text) > TRANSCRIPT_HEAD else "")
    print(f"transcript: {len(result.text)} chars: {head}")
    request = FilingRequest(
        kind="voice",
        transcript=result.text,
        now_local=_clock(now, zone),
        zone=zone,
        sections=[SectionBrief(slug=s[0], name=s[1], hint=s[4]) for s in STARTER_SECTIONS],
    )
    return await _file(request, AiohttpClient(), False)


async def _file(request: FilingRequest, http: AiohttpClient, image: bool) -> int:
    filing = await file_with_fallback(make_classifier(settings), request, http)
    print(f"   filing: {filing.sections or ['other']} ({settings.notes_classifier_provider})")
    print(f"    image: {'yes' if image else 'no'} · confident: {filing.confident}")
    print(f"    title: {filing.title}")
    print(f"     gist: {filing.gist}")
    print(f"      due: {filing.due.isoformat(timespec='minutes') if filing.due else None}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="notes-smoke", description=__doc__)
    parser.add_argument("text", nargs="?", help="a link, or plain text for a Note")
    parser.add_argument(
        "--voice", type=Path, help="an audio file (.ogg .m4a .mp3 .mp4) to file as a Voice"
    )
    parser.add_argument("--now", help='the Capture moment, "YYYY-MM-DD HH:MM" local (default: now)')
    parser.add_argument("--zone", default="UTC", help="the Owner's IANA zone (default: UTC)")
    args = parser.parse_args()
    if args.voice is not None:
        raise SystemExit(asyncio.run(_smoke_voice(args.voice, args.now, args.zone)))
    if not args.text:
        parser.error("give a link, plain text, or --voice FILE")
    raise SystemExit(asyncio.run(_smoke(args.text, args.now, args.zone)))


if __name__ == "__main__":
    main()
