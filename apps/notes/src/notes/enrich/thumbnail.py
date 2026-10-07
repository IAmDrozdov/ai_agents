"""`uv run notes-thumbs`: the Thumbnail a card shows, and a rerunnable backfill (notes ADR-0012)."""

from __future__ import annotations

import argparse
import asyncio
import io

from PIL import Image, ImageOps

from notes.db import Database
from notes.domain import items
from notes.domain.items import Item
from notes.enrich.http import AiohttpClient, FetchError, HttpClient
from notes.enrich.providers import fetch_for, is_social_media, is_youtube
from shared.config import settings
from shared.obs import get_logger

log = get_logger(__name__)

SIZE = 216  # 3x the 72 px card slot
QUALITY = 70
MIME = "image/webp"
# Decoded pixels allowed, not file size: a 150 KB PNG can be 40 Mpx. 16 Mpx is at most 64 MB as RGBA.
MAX_PIXELS = 16_000_000
_ORIENTATIONS = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}


def make(data: bytes) -> bytes | None:
    """A SIZE x SIZE centre crop of `data` as WebP, or None when it is not a readable image."""
    try:
        with Image.open(io.BytesIO(data)) as source:
            source.draft("RGB", (SIZE, SIZE))  # a JPEG decodes straight at a reduced scale
            if source.width * source.height > MAX_PIXELS:
                return None
            turn = _ORIENTATIONS.get(source.getexif().get(0x0112, 1))
            alpha = source.mode in ("RGBA", "LA", "PA") or "transparency" in source.info
            mode = "RGBA" if alpha else "RGB"
            image = source if source.mode in ("RGB", "RGBA", "L", "LA") else source.convert(mode)
            # Shrink before anything else copies the full-size picture.
            scale = SIZE / min(image.size)
            if scale < 1:
                size = (
                    max(SIZE, round(image.width * scale)),
                    max(SIZE, round(image.height * scale)),
                )
                image = image.resize(size, Image.Resampling.LANCZOS, reducing_gap=3.0)
            image = image.convert(mode)
            if turn is not None:
                image = image.transpose(turn)
            square = ImageOps.fit(image, (SIZE, SIZE), Image.Resampling.LANCZOS)
            out = io.BytesIO()
            square.save(out, "WEBP", quality=QUALITY)
            return out.getvalue()
    except (
        Exception
    ) as exc:  # a corrupt image raises more than OSError (SyntaxError for a broken PNG)
        log.info("no thumbnail: %s: %s", exc.__class__.__name__, exc)
        return None


def save(db: Database, item_id: int, image: bytes) -> bool:
    """Make and keep the Item's Thumbnail from `image`; False when there is nothing to keep."""
    thumb = make(image)
    return thumb is not None and items.store_thumb(db, item_id, thumb, MIME)


async def _cover(http: HttpClient, url: str | None) -> bytes | None:
    if not url or not url.lower().startswith(("http://", "https://")):
        return None
    try:
        return (await http.get_image(url))[0]
    except FetchError as exc:
        log.info("no cover from %s: %s", url, exc)
        return None


async def _picture(item: Item, db: Database, http: HttpClient) -> bytes | None:
    preview = await asyncio.to_thread(items.get_preview, db, item.id)
    if preview is not None:
        return preview[0]
    if item.kind != "link" or not item.url:
        return None
    if item.image_url:
        cover = await _cover(http, item.image_url)
        if cover is not None:
            return cover
    elif not (is_social_media(item.url) or is_youtube(item.url)):
        return None  # an article with no cover: its page rarely has one the second time
    # Signed cover URLs (Instagram) expire within days, and a first fetch can fail: ask the provider again.
    try:
        fetched = await fetch_for(item.url, http)
    except FetchError as exc:
        log.info("item %s: no fresh cover: %s", item.id, exc)
        return None
    return await _cover(http, fetched.image_url)


async def backfill(db: Database, http: HttpClient) -> dict[str, int]:
    """Give every Item with a picture but no Thumbnail one; no Classifier call, safe to rerun."""
    counts = {"made": 0, "without": 0}
    for item in await asyncio.to_thread(items.missing_thumbs, db):
        try:
            picture = await _picture(item, db, http)
            made = picture is not None and await asyncio.to_thread(save, db, item.id, picture)
        except Exception:  # one odd Item must not stop the ones after it
            log.exception("item %s: no thumbnail", item.id)
            made = False
        counts["made" if made else "without"] += 1
    return counts


def main() -> None:
    argparse.ArgumentParser(prog="notes-thumbs", description=__doc__).parse_args()
    db = Database(settings.notes_db_path)
    db.init()
    print(asyncio.run(backfill(db, AiohttpClient())))


if __name__ == "__main__":
    main()
