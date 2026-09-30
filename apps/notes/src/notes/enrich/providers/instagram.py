"""Instagram: the official captioned embed page, which renders without a login (ADR-0005)."""

from __future__ import annotations

import html as html_lib
import re
from urllib.parse import urlsplit

from notes.enrich.errors import FetchError
from notes.enrich.http import HttpClient
from notes.enrich.providers import Fetched

_POST = re.compile(r"/(reel|p|tv)/([^/?#]+)")
_PROFILE = re.compile(r"^/([A-Za-z0-9._]+)/?$")
_NOT_PROFILES = {"reel", "reels", "p", "tv", "stories", "explore", "accounts", "direct"}
_USERNAME = re.compile(r'<span class="UsernameText">([^<]*)</span>')
_IMAGE = re.compile(r'<img class="EmbeddedMediaImage"[^>]*?\ssrc="([^"]+)"')
_CAPTION = re.compile(r'<div class="Caption">(.*?)</div>', re.S)
_CAPTION_USERNAME = re.compile(r'<a class="CaptionUsername".*?</a>', re.S)
_COMMENTS = re.compile(r"\s*View all (?:[\d,.]+ )?comments?\s*$", re.I)
_BR = re.compile(r"<br\s*/?>", re.I)
_TAG = re.compile(r"<[^>]+>")


def embed_url(url: str) -> str:
    match = _POST.search(urlsplit(url).path)
    if match is None:
        raise FetchError("not a post link")
    return f"https://www.instagram.com/{match.group(1)}/{match.group(2)}/embed/captioned/"


def _first(pattern: re.Pattern[str], page: str) -> str | None:
    match = pattern.search(page)
    return html_lib.unescape(match.group(1)).strip() or None if match else None


def caption_of(page: str) -> str | None:
    match = _CAPTION.search(page)
    if match is None:
        return None
    body = _CAPTION_USERNAME.sub("", match.group(1))
    text = _TAG.sub("", _BR.sub("\n", body))
    text = re.sub(r"\n{3,}", "\n\n", html_lib.unescape(text)).strip()
    return _COMMENTS.sub("", text).strip() or None


async def fetch(url: str, http: HttpClient) -> Fetched:
    profile = _PROFILE.match(urlsplit(url).path)
    if profile and profile.group(1).lower() not in _NOT_PROFILES:
        return Fetched(source="instagram", author=profile.group(1), title=f"@{profile.group(1)}")
    page = await http.get_html(embed_url(url))
    return Fetched(
        source="instagram",
        author=_first(_USERNAME, page),
        caption=caption_of(page),
        image_url=_first(_IMAGE, page),
    )
