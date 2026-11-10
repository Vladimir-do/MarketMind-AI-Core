"""
router.py — роутер маркетплейсов.
Автоматически определяет какой парсер использовать по URL.
"""

import asyncio

from app.config import logger
from app.parsers.base import BaseParser, ProductData
from app.parsers.ozon import OzonParser
from app.parsers.universal import UniversalParser
from app.parsers.wildberries import WildberriesParser
from app.parsers.yandex_market import YandexMarketParser
from app.searcher import search_ozon
from app.utils.error_research import research_parse_failure
from app.utils.urls import is_ozon_url, is_wildberries_url, is_yandex_market_url

# Все доступные парсеры
PARSERS: list[type[BaseParser]] = [
    WildberriesParser,
    OzonParser,
    YandexMarketParser,
    UniversalParser,
]

MARKETPLACE_EMOJI = {
    "ozon": "🔵",
    "wildberries": "🟣",
    "aliexpress": "🔴",
    "unknown": "⚪",
}


def detect_marketplace(url: str) -> str:
    """Определяет маркетплейс по URL."""
    url = url.lower()
    if is_ozon_url(url):
        return "ozon"
    if is_wildberries_url(url):
        return "wildberries"
    if is_yandex_market_url(url):
        return "yandex_market"
    if "aliexpress" in url:
        return "aliexpress"
    return "unknown"


def get_parser_class(url: str) -> type[BaseParser] | None:
    """Возвращает класс парсера для данного URL."""
    for parser_cls in PARSERS:
        if parser_cls.can_handle(url):
            return parser_cls
    return None


async def fetch_product_auto(url: str) -> ProductData | None:
    """
    Автоматически определяет маркетплейс и парсит товар.
    Для WB — без браузера (быстро).
    Для Ozon — через Playwright (медленнее, ninja-режим).
    """
    marketplace = detect_marketplace(url)
    logger.info(f"{MARKETPLACE_EMOJI.get(marketplace, '⚪')} Парсим {marketplace}: {url[:60]}...")

    if marketplace == "wildberries":
        parser = WildberriesParser()
        return await parser.fetch_product(url)

    elif marketplace == "ozon":
        parser = OzonParser()
        try:
            return await parser.fetch_product(url)
        finally:
            await parser.stop()

    elif marketplace == "yandex_market":
        parser = YandexMarketParser()
        return await parser.fetch_product(url)

    else:
        logger.warning(f"Неизвестный маркетплейс для URL: {url}")
        try:
            await research_parse_failure(
                source="router_unknown_marketplace",
                url=url,
                detail=f"Маркетплейс не поддержан роутером: {marketplace}",
                marketplace=marketplace,
            )
        except Exception as e:
            logger.debug(f"research_parse_failure: {e}")
        return None


async def search_all_marketplaces(
    query: str,
    max_per_site: int = 3,
    *,
    exclude_marketplaces: tuple[str, ...] = (),
) -> dict[str, list[ProductData]]:
    """Ищет товары на маркетплейсах независимо друг от друга."""
    wb_parser = WildberriesParser()
    yandex_parser = YandexMarketParser()
    excluded = set(exclude_marketplaces)

    async def search_wb():
        return await wb_parser.search(query, max_per_site)

    async def search_oz():
        raw_results = await search_ozon(query, max_results=max_per_site)
        return [
            ProductData(
                name=item.get("name", ""),
                price=item.get("price"),
                old_price=None,
                discount_pct=None,
                # Search snippets expose a price but do not prove stock status.
                # Keep availability unknown until a product-detail response provides
                # an explicit in-stock/out-of-stock signal.
                availability="unknown",
                url=item.get("url", ""),
                image_url=item.get("image_url"),
                marketplace="ozon",
            )
            for item in raw_results
        ]

    async def search_yandex():
        return await yandex_parser.search(query, max_per_site)

    results: dict[str, list[ProductData]] = {
        "wildberries": [],
        "ozon": [],
        "yandex_market": [],
    }

    names: list[str] = []
    tasks: list[asyncio.Future | asyncio.Task] = []
    if "wildberries" not in excluded:
        names.append("wildberries")
        tasks.append(search_wb())
    if "ozon" not in excluded:
        names.append("ozon")
        tasks.append(search_oz())
    if "yandex_market" not in excluded:
        names.append("yandex_market")
        tasks.append(search_yandex())

    if tasks:
        gathered = await asyncio.gather(*tasks, return_exceptions=True)
        for name, result in zip(names, gathered, strict=True):
            if isinstance(result, Exception):
                logger.warning(f"Search failed for {name}: {type(result).__name__}: {result}")
                results[name] = []
            else:
                results[name] = result

    return results
