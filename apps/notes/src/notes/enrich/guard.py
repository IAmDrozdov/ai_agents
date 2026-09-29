"""SSRF guard: the one place the Owner chooses what this host connects to."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlsplit

from notes.enrich.errors import FetchError

Resolver = Callable[[str], list[str]]


class UnsafeUrl(FetchError):
    """The link points somewhere this host must not fetch."""


def _resolve(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return [str(info[4][0]) for info in infos]


def assert_fetchable(url: str, *, resolve: Resolver = _resolve) -> None:
    """Raise UnsafeUrl unless the link is http(s), well-formed and resolves to public addresses only."""
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https"):
        raise UnsafeUrl("only http and https links can be fetched")
    if not parts.hostname:
        raise UnsafeUrl("the link has no host")
    # No legitimate target needs userinfo or a backslash; both are how parsers get confused.
    if "@" in parts.netloc or "\\" in url:
        raise UnsafeUrl("the link is not in a supported form")
    try:
        addresses = resolve(parts.hostname)
    except OSError as exc:
        raise UnsafeUrl("the host does not resolve") from exc
    if not addresses:
        raise UnsafeUrl("the host does not resolve")
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise UnsafeUrl("the host does not resolve to an address") from exc
        if not ip.is_global or ip.is_multicast:
            raise UnsafeUrl("the link points at a private address")
