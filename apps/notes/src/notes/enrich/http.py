"""The outbound HTTP boundary: a port the providers talk to, and its aiohttp implementation."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol
from urllib.parse import urljoin

import aiohttp

from notes.enrich.errors import FetchError
from notes.enrich.guard import assert_fetchable

__all__ = ["AiohttpClient", "FetchError", "HttpClient"]

USER_AGENT = "maxi-bot-notes/1.0 (+https://github.com/IAmDrozdov/maxi-bot)"
TIMEOUT_S = 10
MAX_REDIRECTS = 3
MAX_BODY_BYTES = 2_000_000
MAX_IMAGE_BYTES = 1_000_000
_REDIRECTS = {301, 302, 303, 307, 308}


class HttpClient(Protocol):
    async def get_json(self, url: str) -> dict[str, Any]: ...

    async def get_html(self, url: str) -> str: ...

    async def get_image(self, url: str) -> tuple[bytes, str]: ...


class AiohttpClient:
    """Fetches with a short timeout; pages pass the SSRF guard on every redirect hop."""

    async def get_json(self, url: str) -> dict[str, Any]:
        text = await self._get(url, guard=False)
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise FetchError("the endpoint did not answer with JSON") from exc
        if not isinstance(data, dict):
            raise FetchError("unexpected JSON shape")
        return data

    async def get_html(self, url: str) -> str:
        return await self._get(url, guard=True)

    async def get_image(self, url: str) -> tuple[bytes, str]:
        """(bytes, mime) of an image behind the SSRF guard; FetchError if it is not one or too big."""
        body, content_type = await self._fetch(url, guard=True, limit=MAX_IMAGE_BYTES + 1)
        mime = content_type.split(";")[0].strip().lower()
        if not mime.startswith("image/"):
            raise FetchError("not an image")
        if len(body) > MAX_IMAGE_BYTES:
            raise FetchError("image too large")
        return body, mime

    async def _get(self, url: str, *, guard: bool) -> str:
        body, content_type = await self._fetch(url, guard=guard, limit=MAX_BODY_BYTES)
        charset = "utf-8"
        for part in content_type.split(";")[1:]:
            key, _, value = part.strip().partition("=")
            if key.lower() == "charset" and value:
                charset = value.strip("\"'")
        return body.decode(charset, errors="replace")

    async def _fetch(self, url: str, *, guard: bool, limit: int) -> tuple[bytes, str]:
        if guard:
            await asyncio.to_thread(assert_fetchable, url)
        timeout = aiohttp.ClientTimeout(total=TIMEOUT_S)
        headers = {"User-Agent": USER_AGENT, "Accept-Language": "en,ru;q=0.8"}
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                for _ in range(MAX_REDIRECTS + 1):
                    async with session.get(url, allow_redirects=False) as response:
                        location = response.headers.get("Location")
                        if response.status in _REDIRECTS and location:
                            url = urljoin(url, location)
                            if guard:
                                await asyncio.to_thread(assert_fetchable, url)
                            continue
                        if response.status >= 400:
                            raise FetchError(f"HTTP {response.status}")
                        # Metadata lives in the head, so a huge page is cut, not refused.
                        chunks: list[bytes] = []
                        total = 0
                        async for chunk in response.content.iter_chunked(65536):
                            chunks.append(chunk)
                            total += len(chunk)
                            if total >= limit:
                                break
                        return b"".join(chunks)[:limit], response.headers.get("Content-Type", "")
                raise FetchError("too many redirects")
        except aiohttp.ClientError as exc:
            raise FetchError(str(exc) or exc.__class__.__name__) from exc
        except TimeoutError as exc:
            raise FetchError("timed out") from exc
