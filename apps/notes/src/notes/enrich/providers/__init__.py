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


def is_youtube(url: str) -> bool:
    return bare_host(url) in ("youtube.com", "youtu.be", "music.youtube.com")


def is_social_media(url: str) -> bool:
    """Instagram or TikTok: a post/reel with a caption, never an article."""
    host = bare_host(url)
    return host == "instagram.com" or host == "tiktok.com" or host.endswith(".tiktok.com")


def provider_for(url: str) -> Provider:
    from notes.enrich.providers import generic, instagram, tiktok, youtube

    host = bare_host(url)
    if is_youtube(url):
        return youtube.fetch
    if host == "instagram.com":
        return instagram.fetch
    if is_social_media(url):
        return tiktok.fetch
    return generic.fetch


async def fetch_for(url: str, http: HttpClient) -> Fetched:
    return await provider_for(url)(url, http)
