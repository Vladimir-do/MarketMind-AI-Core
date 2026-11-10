"""Helpers for resolving product images during import parsing."""

from __future__ import annotations

from functools import lru_cache
from html import unescape
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from bs4 import BeautifulSoup

# Source pages are fetched server-side during file import. Keep this list
# deliberately narrow: imported URLs must not turn the importer into an SSRF
# proxy. Image URLs discovered inside an allowed page may use a separate CDN.
_ALLOWED_SOURCE_HOSTS = (
    "market.yandex.ru",
    "market.yandex.by",
    "market.yandex.kz",
    "market.yandex.uz",
    "ozon.ru",
    "wildberries.ru",
    "wb.ru",
    "funpay.com",
)

_PLACEHOLDER_IMAGE_HOSTS = {
    "example.com",
    "example.org",
    "example.net",
    "example.test",
    "img.test",
}

_USER_AGENT = "MarketMind-AI-Importer/1.0"


def _is_allowed_source_url(value: str | None) -> bool:
    """Return whether a URL may be fetched as an imported product page."""
    url = unescape((value or "").strip())
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not host:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    if port not in {None, 80, 443}:
        return False
    return any(host == domain or host.endswith("." + domain) for domain in _ALLOWED_SOURCE_HOSTS)


class _SafeSourceRedirectHandler(HTTPRedirectHandler):
    """Prevent an allowed marketplace page redirecting the importer elsewhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _is_allowed_source_url(newurl):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def resolve_image_url_from_source(source_url: str | None) -> str | None:
    """Fetch an allowed marketplace product page and return its image URL."""
    if not _is_allowed_source_url(source_url):
        return None
    url = _normalize_url(source_url)
    if not url:
        return None
    return _resolve_image_url_cached(url)


@lru_cache(maxsize=512)
def _resolve_image_url_cached(source_url: str) -> str | None:
    try:
        request = Request(
            source_url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept-Language": "ru,en;q=0.9",
            },
        )
        opener = build_opener(_SafeSourceRedirectHandler())
        with opener.open(request, timeout=12) as response:
            content_type = response.headers.get("Content-Type", "")
            if "html" not in content_type.lower() and "xml" not in content_type.lower():
                return None
            raw = response.read(1_200_000)
    except Exception:
        return None

    soup = BeautifulSoup(raw, "lxml")
    for selector, attr in (
        ('meta[property="og:image"]', "content"),
        ('meta[name="twitter:image"]', "content"),
        ('meta[itemprop="image"]', "content"),
    ):
        node = soup.select_one(selector)
        if not node:
            continue
        url = _normalize_url(node.get(attr), base_url=source_url)
        if url:
            return url

    for selector in (
        '[itemprop="image"]',
        "img[class*='product']",
        "div[class*='product'] img",
        "div[class*='gallery'] img",
        "main img",
        "article img",
        "img",
    ):
        node = soup.select_one(selector)
        if not node:
            continue
        src = _normalize_url(node.get("src") or node.get("data-src") or node.get("content"), base_url=source_url)
        if src:
            return src
    return None


def _normalize_url(value: str | None, *, base_url: str | None = None) -> str | None:
    url = unescape((value or "").strip())
    if not url:
        return None
    if url.startswith("//"):
        url = f"https:{url}"
    elif base_url and not urlparse(url).scheme:
        url = urljoin(base_url, url)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if (parsed.hostname or "").lower() in _PLACEHOLDER_IMAGE_HOSTS:
        return None
    return url
