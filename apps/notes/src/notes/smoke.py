"""`uv run notes-smoke <url-or-text | --voice FILE>`: Capture and enrich one input on a throwaway database, print the Item (ADR-001)."""

from __future__ import annotations

import argparse
import asyncio
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from notes.capture import Attachment, Origin, Payload, Text, acknowledgement_of, capture
from notes.classify import make_classifier
from notes.db import Database
from notes.domain import clock, items
from notes.domain.reminders import Notice
from notes.enrich.http import AiohttpClient
from notes.enrich.pipeline import enrich_item
from notes.enrich.voice import Download
from shared.config import settings

TRANSCRIPT_HEAD = 400


@contextmanager
def _database(path: Path | None) -> Iterator[Database]:
    """A temp database deleted on exit, or the given file used in place."""
    if path is not None:
        db = Database(str(path))
        db.init()
        yield db
        return
    tmp = Path(tempfile.mkdtemp(prefix="notes-smoke-"))
    try:
        db = Database(str(tmp / "notes.sqlite3"))
        db.init()
        yield db
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def _print_notify(notice: Notice) -> None:
    print(f"acknowledge: {acknowledgement_of(notice.item)}")
    print(f" due line: {notice.due}")


async def _run(
    payload: Payload,
    *,
    db_path: Path | None,
    now: datetime | None,
    zone: str | None,
    download: Download,
) -> int:
    with _database(db_path) as db:
        if zone is not None:
            clock.remember_zone(db, zone)
        classifier = make_classifier(settings)
        captured = await capture(db, payload, Origin(None, None), classifier=classifier, now=now)
        print(
            f"     kind: {captured.item.kind} ({captured.outcome}) · acknowledge: {captured.acknowledgement}"
        )
        if captured.due is not None:
            print(f" due line: {captured.due}")
        if captured.enrich:
            await enrich_item(
                db,
                captured.item.id,
                http=AiohttpClient(),
                classifier=classifier,
                notify=_print_notify,
                download=download,
                now=now,
            )
        item = items.get_item(db, captured.item.id)
        if item is None:
            print("item vanished")
            return 1
        transcript = item.transcript or ""
        head = transcript[:TRANSCRIPT_HEAD] + ("…" if len(transcript) > TRANSCRIPT_HEAD else "")
        for label, value in (
            ("source", item.source),
            ("title", item.title),
            ("author", item.author),
            ("caption", item.caption),
            ("transcript", head or None),
            ("filing", [s.slug for s in item.sections]),
            ("gist", item.gist),
            ("due", clock.iso(item.due_at) if item.due_at else None),
            ("thumbnail", "yes" if item.thumb else "no"),
            ("enrichment", item.enrichment_status),
            ("error", item.enrichment_error),
        ):
            print(f"{label:>10}: {value}")
        return 0 if item.enrichment_status == "done" and not item.enrichment_error else 1


async def _no_download(file_id: str) -> bytes:
    raise RuntimeError("no download in the smoke runner")


def _voice(path: Path) -> tuple[Attachment, Download]:
    mime = "video/mp4" if path.suffix == ".mp4" else "audio/ogg"
    attachment = Attachment(
        file_id=str(path), mime=mime, size=path.stat().st_size, duration_s=0, speech=True
    )
    return attachment, lambda file_id: asyncio.to_thread(Path(file_id).read_bytes)


def main() -> None:
    parser = argparse.ArgumentParser(prog="notes-smoke", description=__doc__)
    parser.add_argument("text", nargs="?", help="a link, or plain text for a Note")
    parser.add_argument(
        "--voice",
        type=Path,
        help="an audio file (.ogg .m4a .mp3 .mp4) to file as a Voice (paid STT)",
    )
    parser.add_argument("--now", help='the Capture moment, "YYYY-MM-DD HH:MM" local (default: now)')
    parser.add_argument(
        "--zone", help="the Owner's IANA zone to store (default: keep the Database's)"
    )
    parser.add_argument(
        "--db",
        type=Path,
        help="use this database file in place (written to; a throwaway or Backup copy)",
    )
    args = parser.parse_args()
    now = (
        clock.local_to_utc(datetime.strptime(args.now, "%Y-%m-%d %H:%M"), args.zone or "UTC")
        if args.now
        else None
    )
    if args.voice is not None:
        payload, download = _voice(args.voice)
    elif args.text:
        payload, download = Text(words=args.text), _no_download
    else:
        parser.error("give a link, plain text, or --voice FILE")
    raise SystemExit(
        asyncio.run(_run(payload, db_path=args.db, now=now, zone=args.zone, download=download))
    )


if __name__ == "__main__":
    main()
