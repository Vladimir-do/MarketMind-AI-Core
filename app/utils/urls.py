from __future__ import annotations

from urllib.parse import urlparse

YANDEX_MARKET_HOSTS = (
    "market.yandex.ru",
    "market.yandex.by",
    "market.yandex.kz",
    "market.yandex.uz",
)

OZON_HOSTS = ("ozon.ru",)

WILDBERRIES_HOSTS = ("wildberries.ru", "wb.ru")

FUNPAY_HOSTS = ("funpay.com",)


def _host_matches(host: str, domains: tuple[str, ...]) -> bool:
    # Exact host or a proper subdomain only — a plain substring check (e.g.
    # "ozon.ru" in host) also matches attacker-controlled hosts like
    # "ozon.ru.evil.com", which would route the URL to a real fetch/browser
    # navigation against an arbitrary host (SSRF).
    return any(host == item or host.endswith("." + item) for item in domains)


def is_yandex_market_url(url: str) -> bool:
    host = (urlparse(url or "").netloc or "").lower()
    return _host_matches(host, YANDEX_MARKET_HOSTS)


def is_ozon_url(url: str) -> bool:
    host = (urlparse(url or "").netloc or "").lower()
    return _host_matches(host, OZON_HOSTS)


def is_wildberries_url(url: str) -> bool:
    host = (urlparse(url or "").netloc or "").lower()
    return _host_matches(host, WILDBERRIES_HOSTS)


def is_funpay_url(url: str) -> bool:
    host = (urlparse(url or "").netloc or "").lower()
    return _host_matches(host, FUNPAY_HOSTS)
