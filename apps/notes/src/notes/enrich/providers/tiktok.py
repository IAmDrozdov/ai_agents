"""TikTok: oEmbed gives the caption as the title, plus author and thumbnail."""

from __future__ import annotations

from urllib.parse import quote, urlsplit, urlunsplit

from notes.enrich.http import HttpClient
from notes.enrich.providers import Fetched

OEMBED = "https://www.tiktok.com/oembed?url={url}"


async def fetch(url: str, http: HttpClient) -> Fetched:
    parts = urlsplit(url)
    bare = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    data = await http.get_json(OEMBED.format(url=quote(bare, safe="")))
    return Fetched(
        source="tiktok",
        title=data.get("title"),
        author=data.get("author_name"),
        image_url=data.get("thumbnail_url"),
    )
