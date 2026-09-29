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

USER_AGENT = "ai-agents-notes/1.0 (+https://github.com/IAmDrozdov/ai_agents)"
TIMEOUT_S = 10
MAX_REDIRECTS = 3
MAX_BODY_BYTES = 2_000_000
_REDIRECTS = {301, 302, 303, 307, 308}


class HttpClient(Protocol):
    async def get_json(self, url: str) -> dict[str, Any]: ...

    async def get_html(self, url: str) -> str: ...


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

    async def _get(self, url: str, *, guard: bool) -> str:
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
                        body = await response.content.read(MAX_BODY_BYTES)
                        return body.decode(response.charset or "utf-8", errors="replace")
                raise FetchError("too many redirects")
        except aiohttp.ClientError as exc:
            raise FetchError(str(exc) or exc.__class__.__name__) from exc
        except TimeoutError as exc:
            raise FetchError("timed out") from exc
