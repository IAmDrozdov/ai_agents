"""YouTube: oEmbed for title/author/thumbnail, the watch page's description when it is readable."""

from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, quote, urlsplit

from notes.domain.urls import normalize_url
from notes.enrich.errors import FetchError
from notes.enrich.http import HttpClient
from notes.enrich.metadata import page_metadata
from notes.enrich.providers import Fetched

OEMBED = "https://www.youtube.com/oembed?url={url}&format=json"


def video_id(url: str) -> str | None:
    canonical = urlsplit(normalize_url(url))
    if canonical.path != "/watch":
        return None
    values = parse_qs(canonical.query).get("v")
    return values[0] if values else None


async def fetch(url: str, http: HttpClient) -> Fetched:
    vid = video_id(url)
    if vid is None:
        raise FetchError("not a video link")
    watch_url = f"https://www.youtube.com/watch?v={vid}"
    data = await http.get_json(OEMBED.format(url=quote(watch_url, safe="")))
    caption: str | None = None
    try:
        page = await http.get_html(watch_url)
        caption = (await asyncio.to_thread(page_metadata, page)).description
    except FetchError:
        pass
    return Fetched(
        source="youtube",
        title=data.get("title"),
        author=data.get("author_name"),
        image_url=data.get("thumbnail_url"),
        caption=caption,
    )
