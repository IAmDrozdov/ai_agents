"""YouTube metadata, captions, and audio access via yt-dlp.

No ffmpeg anywhere here: captions are read as-is, and the audio-download fallback
picks a single audio-only stream and hands its raw bytes to OpenAI's transcription
API without transcoding.
"""

from __future__ import annotations

import json
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared.obs import get_logger

log = get_logger(__name__)

_BRACKET_CUE = re.compile(r"^\[[^\]]+\]$")
_VTT_TIMESTAMP = re.compile(r"-->")
_VTT_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")

# Preference order when a language has more than one caption format on offer.
# json3 carries per-segment text with no rolling-duplicate problem; vtt is the
# fallback for the rare track that only ships as vtt/srv/ttml.
_CAPTION_EXT_PREFERENCE = ("json3", "vtt")

# timedtext answers 429 intermittently; a failed fetch otherwise falls through to paid STT.
_CAPTION_ATTEMPTS = 3
_CAPTION_BACKOFF_S = 2.0


class YouTubeError(RuntimeError):
    """A video could not be probed, its captions fetched, or its audio downloaded."""


_VIDEO_ID_RE = re.compile(r"(?:[?&]v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{11})")


def canonical_watch_url(url: str) -> str | None:
    """A single-video `watch?v=` URL for `url`, or None if it names no single video.

    Only single videos are ever meant to reach yt-dlp here: a playlist, channel or
    search-results URL has no video id to extract and is refused by callers instead of
    being handed to yt-dlp's own (much broader) extractor routing.
    """
    match = _VIDEO_ID_RE.search(url)
    return f"https://www.youtube.com/watch?v={match.group(1)}" if match else None


@dataclass(frozen=True)
class VideoMeta:
    video_id: str
    title: str
    duration_s: float
    language: str | None
    subtitle_langs: list[str]
    automatic_caption_langs: list[str]


def _ydl_opts(proxy: str | None = None, **overrides: Any) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,  # `quiet` alone still writes the download progress bar to stdout
        "noplaylist": True,
        "skip_download": True,
        "cachedir": False,  # the container filesystem is read-only
        # Defense in depth alongside canonical_watch_url(): even if a caller ever
        # passes yt-dlp a raw URL, only the youtube extractor (never a playlist/
        # channel/search/generic one) is allowed to claim it.
        "allowed_extractors": ["^youtube$"],
    }
    if proxy:
        opts["proxy"] = proxy
    opts.update(overrides)
    return opts


def _is_bot_check(exc: Exception) -> bool:
    text = str(exc).lower()
    return "sign in to confirm" in text or "not a bot" in text or " 403" in text


def _wrap_error(exc: Exception, *, proxied: bool) -> YouTubeError:
    log.warning("yt_dub: yt-dlp failed (proxied=%s): %s", proxied, exc)
    if _is_bot_check(exc):
        if proxied:
            return YouTubeError(
                "YouTube is blocking the configured proxy too (\"sign in to confirm you're "
                'not a bot"). The owner needs a fresh proxy identity or another YTDLP_PROXY '
                "(ADR-014, Revisit when)."
            )
        return YouTubeError(
            "YouTube is blocking this server's IP (\"sign in to confirm you're not a "
            'bot"). This is a known risk of running yt-dlp from a datacenter host — '
            "the owner can route yt-dlp through a proxy with YTDLP_PROXY (ADR-014)."
        )
    return YouTubeError(str(exc))


def extract_info(url: str, *, proxy: str | None = None) -> dict[str, Any]:
    """Single yt-dlp metadata fetch, no download. Free — safe to call before billing."""
    import yt_dlp

    canonical = canonical_watch_url(url)
    if canonical is None:
        raise YouTubeError(
            "Only single YouTube videos are supported — not playlists, channels or search results."
        )

    try:
        with yt_dlp.YoutubeDL(_ydl_opts(proxy)) as ydl:
            info = ydl.extract_info(canonical, download=False)
    except Exception as exc:  # yt-dlp raises broadly by design (DownloadError etc.)
        raise _wrap_error(exc, proxied=bool(proxy)) from exc

    if info is None:
        raise YouTubeError("yt-dlp returned no metadata for this URL.")
    return info


def meta_from_info(info: dict[str, Any]) -> VideoMeta:
    return VideoMeta(
        video_id=str(info.get("id") or ""),
        title=str(info.get("title") or "video"),
        duration_s=float(info["duration"]),
        language=info.get("language"),
        subtitle_langs=sorted((info.get("subtitles") or {}).keys()),
        automatic_caption_langs=sorted((info.get("automatic_captions") or {}).keys()),
    )


def _pick_lang(tracks: dict[str, list[dict[str, Any]]], preferred: list[str]) -> str | None:
    if not tracks:
        return None
    for lang in preferred:
        if lang in tracks:
            return lang
        base = lang.split("-")[0]
        match = next((code for code in tracks if code.split("-")[0] == base), None)
        if match:
            return match
    return None


def _pick_entry(tracks: list[dict[str, Any]]) -> tuple[dict[str, Any], str] | None:
    for ext in _CAPTION_EXT_PREFERENCE:
        entry = next((t for t in tracks if t.get("ext") == ext), None)
        if entry:
            return entry, ext
    return None


def _parse_json3(raw: bytes) -> str:
    data = json.loads(raw)
    lines: list[str] = []
    for event in data.get("events", []):
        segs = event.get("segs")
        if not segs:
            continue
        text = "".join(seg.get("utf8", "") for seg in segs).replace("\n", " ").strip()
        if not text or _BRACKET_CUE.match(text):
            continue
        lines.append(text)
    return _WHITESPACE.sub(" ", " ".join(lines)).strip()


def _parse_vtt(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    lines: list[str] = []
    seen: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line == "WEBVTT" or line.isdigit() or _VTT_TIMESTAMP.search(line):
            continue
        line = _VTT_TAG.sub("", line).strip()
        if not line or _BRACKET_CUE.match(line) or line == seen:
            continue  # auto-caption VTT repeats the trailing line of the previous cue
        lines.append(line)
        seen = line
    return _WHITESPACE.sub(" ", " ".join(lines)).strip()


def _read_caption(url: str, proxy: str | None) -> bytes:
    """Caption track bytes: direct with 429 retries, then one attempt through `proxy`."""
    import yt_dlp

    attempt = 0
    while True:
        attempt += 1
        try:
            with yt_dlp.YoutubeDL(_ydl_opts()) as ydl:
                return ydl.urlopen(url).read()
        except Exception as exc:
            if attempt < _CAPTION_ATTEMPTS and "429" in str(exc):
                log.info("yt_dub: caption fetch rate-limited, retry %d", attempt)
                time.sleep(_CAPTION_BACKOFF_S * attempt)
                continue
            if not proxy:
                raise
            log.info("yt_dub: direct caption fetch failed (%s), trying the proxy", exc)
            break

    with yt_dlp.YoutubeDL(_ydl_opts(proxy)) as ydl:
        return ydl.urlopen(url).read()


def fetch_captions(
    info: dict[str, Any],
    *,
    preferred: list[str],
    proxy: str | None = None,
) -> tuple[str, str] | None:
    """Manual subtitles first, then auto-captions; `preferred` languages in order.

    Returns `(text, source)` where source is `"subtitles"` or `"auto_captions"`, or
    None if no track exists in a preferred language.
    """
    for key, source in (("subtitles", "subtitles"), ("automatic_captions", "auto_captions")):
        tracks_by_lang: dict[str, list[dict[str, Any]]] = info.get(key) or {}
        lang = _pick_lang(tracks_by_lang, preferred)
        if lang is None:
            continue
        picked = _pick_entry(tracks_by_lang[lang])
        if picked is None:
            continue
        entry, ext = picked
        try:
            raw = _read_caption(entry["url"], proxy)
        except Exception as exc:
            log.warning("yt_dub: caption fetch failed lang=%s ext=%s: %s", lang, ext, exc)
            continue
        text = _parse_json3(raw) if ext == "json3" else _parse_vtt(raw)
        if text:
            return text, source
    return None


def download_audio(url: str, *, max_bytes: int, proxy: str | None = None) -> tuple[bytes, str]:
    """Fallback only: download the smallest audio-only stream, no transcoding.

    Raises `YouTubeError` if the result is over `max_bytes` (OpenAI's transcription
    input cap) — splitting it would require ffmpeg, which this deployment does not
    have (ADR-008).
    """
    import yt_dlp

    canonical = canonical_watch_url(url)
    if canonical is None:
        raise YouTubeError(
            "Only single YouTube videos are supported — not playlists, channels or search results."
        )

    with tempfile.TemporaryDirectory() as tmp:
        opts = _ydl_opts(
            proxy,
            format="worstaudio/worst",
            outtmpl=str(Path(tmp) / "%(id)s.%(ext)s"),
            skip_download=False,
            # yt-dlp skips the download up front when Content-Length is over the cap;
            # without that header the size is only checked after the download.
            max_filesize=max_bytes,
        )
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(canonical, download=True)
                path = Path(ydl.prepare_filename(info))
        except Exception as exc:
            raise _wrap_error(exc, proxied=bool(proxy)) from exc

        limit = (
            f"the {max_bytes / 1024 / 1024:.0f} MB transcription limit. This video has no captions, "
            "and ffmpeg-based splitting is not available on this deployment."
        )
        if not path.exists():
            # yt-dlp skips an over-cap stream with a known size and still reports success.
            raise YouTubeError(
                f"yt-dlp produced no audio file, most likely because it is over {limit}"
            )
        size = path.stat().st_size
        if size > max_bytes:
            raise YouTubeError(f"Downloaded audio is {size / 1024 / 1024:.1f} MB, over {limit}")
        return path.read_bytes(), path.suffix.lstrip(".") or "m4a"
