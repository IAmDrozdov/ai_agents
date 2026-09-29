"""URL normalisation (the dedupe key) and extraction from a message, as pure functions."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = frozenset(
    {"fbclid", "gclid", "igsh", "igshid", "si", "feature", "ref", "ref_src"}
)
_INSTAGRAM_POST = re.compile(r"^/(reel|p|tv)/([^/?#]+)")
_YOUTUBE_SHORTS = re.compile(r"^/shorts/([^/?#]+)")
_URL = re.compile(r"https?://[^\s<>\"'«»]+", re.IGNORECASE)
_TRAILING_PUNCTUATION = ".,;:!?)]}\"'»«"
_CLOSERS = {")": "(", "]": "[", "}": "{"}
_DEFAULT_PORTS = {("http", 80), ("https", 443)}


@dataclass(frozen=True)
class Extracted:
    urls: tuple[str, ...]
    annotation: str


def is_http_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018 — raises on an out-of-range or non-numeric port
    except ValueError:
        return False
    return parts.scheme.lower() in ("http", "https") and bool(parts.hostname)


def _strip_trailing(url: str) -> str:
    """Drop punctuation glued to a link; a bracket that closes one inside the link stays."""
    while url and url[-1] in _TRAILING_PUNCTUATION:
        last = url[-1]
        if last in _CLOSERS and url.count(_CLOSERS[last]) >= url.count(last):
            break
        url = url[:-1]
    return url


def extract_urls(text: str, *, linked: Iterable[str] = ()) -> Extracted:
    """Links in a message (plain, then those behind text) and the Owner's remaining words."""
    found = [_strip_trailing(match.group(0)) for match in _URL.finditer(text)]
    urls: list[str] = []
    for url in [*found, *linked]:
        if is_http_url(url) and url not in urls:
            urls.append(url)
    # The stripped punctuation stays with the words, the link itself goes.
    remainder = _URL.sub(lambda match: match.group(0)[len(_strip_trailing(match.group(0))) :], text)
    return Extracted(urls=tuple(urls), annotation=" ".join(remainder.split()))


def _is_tracking(key: str) -> bool:
    return key.startswith("utm_") or key in TRACKING_PARAMS


def normalize_url(url: str) -> str:
    """Canonical form of a link so that two ways of sharing the same thing collide."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            host = host[len(prefix) :]
    path = parts.path
    query = parse_qsl(parts.query, keep_blank_values=True)

    if host == "youtu.be":
        host, path, query = "youtube.com", "/watch", [("v", path.strip("/").split("/")[0])]
    elif host == "youtube.com":
        if shorts := _YOUTUBE_SHORTS.match(path):
            path, query = "/watch", [("v", shorts.group(1))]
        elif path == "/watch":
            query = [(key, value) for key, value in query if key == "v"]
    elif host == "instagram.com" and (post := _INSTAGRAM_POST.match(path)):
        path, query = f"/{post.group(1)}/{post.group(2)}", []

    query = sorted((key, value) for key, value in query if not _is_tracking(key))
    port = parts.port
    netloc = host if port is None or (scheme, port) in _DEFAULT_PORTS else f"{host}:{port}"
    return urlunsplit((scheme, netloc, path.rstrip("/"), urlencode(query), ""))
