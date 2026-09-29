"""One provider per Source; `fetch_for` picks by host."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from notes.enrich.http import HttpClient


@dataclass(frozen=True)
class Fetched:
    source: str
    title: str | None = None
    author: str | None = None
    caption: str | None = None
    image_url: str | None = None


Provider = Callable[[str, HttpClient], Awaitable[Fetched]]


def bare_host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            host = host[len(prefix) :]
    return host


def provider_for(url: str) -> Provider:
    from notes.enrich.providers import generic, instagram, tiktok, youtube

    host = bare_host(url)
    if host in ("youtube.com", "youtu.be"):
        return youtube.fetch
    if host == "instagram.com":
        return instagram.fetch
    if host == "tiktok.com" or host.endswith(".tiktok.com"):
        return tiktok.fetch
    return generic.fetch


async def fetch_for(url: str, http: HttpClient) -> Fetched:
    return await provider_for(url)(url, http)
