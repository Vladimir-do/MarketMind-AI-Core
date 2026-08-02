from __future__ import annotations

from urllib.parse import urlparse

YANDEX_MARKET_HOSTS = (
    "market.yandex.ru",
    "market.yandex.by",
    "market.yandex.kz",
    "market.yandex.uz",
)


def is_yandex_market_url(url: str) -> bool:
    host = (urlparse(url or "").netloc or "").lower()
    return any(host == item or host.endswith("." + item) for item in YANDEX_MARKET_HOSTS)
