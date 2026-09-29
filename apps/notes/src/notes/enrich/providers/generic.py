"""Any other page: its metadata, with the domain as the Source."""

from __future__ import annotations

import asyncio

from notes.enrich.http import HttpClient
from notes.enrich.metadata import page_metadata
from notes.enrich.providers import Fetched, bare_host


async def fetch(url: str, http: HttpClient) -> Fetched:
    page = await http.get_html(url)
    meta = await asyncio.to_thread(page_metadata, page)
    return Fetched(
        source=bare_host(url),
        title=meta.title,
        author=meta.author,
        caption=meta.description,
        image_url=meta.image,
    )
