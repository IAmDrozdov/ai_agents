"""Fetch a web page and extract its main article as Markdown.

Interface-layer utility (ADR-005 thin adapter): turns a link into the same
Markdown `.md` payload the document flow already understands, so a URL reuses
the agent-pick → estimate → enqueue path with no workflow changes. Keeps the
scraping dependency out of `shared/` and the workflows.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from shared.obs import get_logger

log = get_logger(__name__)

_ALLOWED_SCHEMES = {"http", "https"}
_REDIRECT_CODES = {301, 302, 303, 307, 308}
_MAX_REDIRECTS = 2
_PROBE_TIMEOUT_S = 10
_USER_AGENT = "maxi-bot-bot/1.0"


class ScrapeError(Exception):
    """User-facing failure while fetching or extracting a link."""


@dataclass(frozen=True)
class ScrapedArticle:
    title: str
    markdown: str
    url: str


_SLUG_RE = re.compile(r"[^0-9A-Za-z]+")


def _slugify(value: str, fallback: str = "article") -> str:
    slug = _SLUG_RE.sub("-", value.strip()).strip("-").lower()[:60].strip("-")
    return slug or fallback


def _is_public_address(host: str) -> bool:
    """False for anything that resolves onto our own network or the metadata service."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError:
        return False
    if not infos:
        return False
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global or address.is_multicast:
            return False
    return True


def assert_fetchable(url: str) -> None:
    """Guard the one place a user gets to choose what this host connects to.

    The bot shares a Docker network with the Mini App and can reach the
    cloud metadata service, so an unchecked URL turns the scraper into a reader
    of internal endpoints. Raises ScrapeError when the target is not public.
    """
    parts = urlsplit(url)
    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        raise ScrapeError("Only http:// and https:// links are supported.")
    if not parts.hostname:
        raise ScrapeError("That link has no host in it.")
    # `urlsplit` and the urllib3 stack trafilatura fetches through can disagree on
    # which host an authority like "169.254.169.254\@1.1.1.1" names — no legitimate
    # scrape target needs userinfo or a backslash, so refuse both outright, then
    # cross-check the parser trafilatura will actually use before trusting this one.
    if "@" in parts.netloc or "\\" in url:
        raise ScrapeError("That link isn't in a supported form.")
    import urllib3.util

    fetch_host = urllib3.util.parse_url(url).host
    if (fetch_host or "").lower() != parts.hostname.lower():
        raise ScrapeError("That link isn't in a supported form.")
    if not _is_public_address(parts.hostname):
        raise ScrapeError("That link points at a private address, so I won't fetch it.")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _resolve_redirects(url: str) -> str:
    """Walk redirects without reading bodies, vetting each hop; returns the final URL."""
    opener = urllib.request.build_opener(_NoRedirect())
    for _ in range(_MAX_REDIRECTS + 1):
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with opener.open(request, timeout=_PROBE_TIMEOUT_S):
                return url
        except urllib.error.HTTPError as exc:
            location = exc.headers.get("Location") if exc.code in _REDIRECT_CODES else None
            if not location:
                return url  # 4xx/5xx: let the real fetch report it
            url = urljoin(url, location)
            assert_fetchable(url)
        except (urllib.error.URLError, OSError, ValueError):
            return url
    raise ScrapeError("That link redirects too many times.")


def scrape_url(url: str) -> ScrapedArticle:
    """Blocking: download `url` and extract its main content as Markdown.

    Raises ScrapeError with a message that is safe to show the user.
    """
    import trafilatura

    assert_fetchable(url)
    url = _resolve_redirects(url)
    response = trafilatura.fetch_response(url, decode=True)
    if response is None or not response.html:
        raise ScrapeError(
            "Couldn't fetch that link — it may be offline, private, or blocking bots."
        )
    # Redirects were vetted hop by hop above; this catches a server that answers
    # differently the second time. `response.url` is often just a path, so resolve
    # it against the request URL before comparing hosts.
    final_url = urljoin(url, response.url or "")
    if urlsplit(final_url).hostname != urlsplit(url).hostname:
        assert_fetchable(final_url)
    downloaded = response.html

    markdown = trafilatura.extract(
        downloaded,
        output_format="markdown",
        include_comments=False,
        include_tables=True,
        favor_precision=True,
    )
    if not markdown or not markdown.strip():
        raise ScrapeError("Couldn't find readable article text on that page.")

    title = ""
    try:
        meta = trafilatura.extract_metadata(downloaded)
        if meta and meta.title:
            title = meta.title.strip()
    except Exception:
        log.exception("scrape: metadata extraction failed")

    body = markdown.strip()
    # Prepend the title as an H1 when the extraction didn't already lead with one,
    # so chapter splitting and the delivered file both carry a heading.
    if title and not body.lstrip().startswith("#"):
        body = f"# {title}\n\n{body}"

    log.info("scrape: %s -> %d chars (title=%r)", url, len(body), title)
    return ScrapedArticle(title=title, markdown=body, url=url)


def filename_for(article: ScrapedArticle) -> str:
    """A `.md` filename derived from the article title (URL as fallback)."""
    return f"{_slugify(article.title or article.url)}.md"
