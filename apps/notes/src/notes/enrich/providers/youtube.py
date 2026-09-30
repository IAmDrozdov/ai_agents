"""YouTube: oEmbed for title/author/thumbnail, the watch page's description, and captions on demand."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from notes.domain.urls import normalize_url
from notes.enrich.errors import FetchError
from notes.enrich.http import HttpClient
from notes.enrich.metadata import page_metadata
from notes.enrich.providers import Fetched
from shared.obs import get_logger

log = get_logger(__name__)

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


TRANSCRIPT_TIMEOUT_S = 25
TRANSCRIPT_MAX_CHARS = 3000
_LANG_PREFERENCE = ("ru", "en")


def _pick_captions(info: dict[str, Any]) -> str | None:
    """URL of a json3 caption track: manual before automatic, the video's language, then ru, en."""
    spoken = info.get("language")
    for pool in (info.get("subtitles") or {}, info.get("automatic_captions") or {}):
        for lang in (spoken, *_LANG_PREFERENCE):
            for track in pool.get(lang) or ():
                if track.get("ext") == "json3" and track.get("url"):
                    return track["url"]
    return None


def _json3_text(payload: dict[str, Any]) -> str:
    events = payload.get("events") or []
    words = ("".join(seg.get("utf8", "") for seg in e.get("segs") or ()) for e in events)
    return " ".join(" ".join(w.split()) for w in words if w.strip())


def _extract_info(url: str) -> dict[str, Any]:
    import yt_dlp

    options = {"skip_download": True, "quiet": True, "no_warnings": True, "noplaylist": True}
    with yt_dlp.YoutubeDL(options) as ydl:
        return ydl.extract_info(url, download=False) or {}


async def transcript(url: str, http: HttpClient) -> str | None:
    """The start of the video's captions as plain text; None when there are none or anything fails."""
    vid = video_id(url)
    if vid is None:
        return None
    try:
        info = await asyncio.wait_for(
            asyncio.to_thread(_extract_info, f"https://www.youtube.com/watch?v={vid}"),
            TRANSCRIPT_TIMEOUT_S,
        )
        track = _pick_captions(info)
        if track is None:
            return None
        text = _json3_text(await http.get_json(track))
    except Exception as exc:
        log.info("no transcript for %s: %s", vid, exc.__class__.__name__)
        return None
    return text[:TRANSCRIPT_MAX_CHARS] or None
