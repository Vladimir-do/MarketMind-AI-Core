"""Helpers for resolving product images during import parsing."""

from __future__ import annotations

from functools import lru_cache
from html import unescape
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

_PLACEHOLDER_IMAGE_HOSTS = {
    "example.com",
    "example.org",
    "example.net",
    "example.test",
    "img.test",
}

_USER_AGENT = "MarketMind-AI-Importer/1.0"


def resolve_image_url_from_source(source_url: str | None) -> str | None:
    """Fetch a product page and return the first usable image URL, if any."""
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
        with urlopen(request, timeout=12) as response:
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
