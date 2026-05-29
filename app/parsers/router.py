"""
router.py — роутер маркетплейсов.
Автоматически определяет какой парсер использовать по URL.
"""
from app.config import logger
from app.parsers.base import BaseParser, ProductData
from app.parsers.wildberries import WildberriesParser
from app.parsers.ozon import OzonParser
from app.parsers.yandex_market import YandexMarketParser, is_yandex_market_url
from app.parsers.universal import UniversalParser
from app.utils.error_research import research_parse_failure

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
    if "ozon.ru" in url:
        return "ozon"
    if "wildberries.ru" in url or "wb.ru" in url:
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
        await parser.start()
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


async def search_all_marketplaces(query: str, max_per_site: int = 3) -> dict[str, list[ProductData]]:
    """Ищет товары на всех маркетплейсах одновременно."""
    import asyncio

    wb_parser = WildberriesParser()

    async def search_wb():
        return await wb_parser.search(query, max_per_site)

    # WB можем делать параллельно, Ozon через браузер — последовательно
    wb_results = await search_wb()

    return {
        "wildberries": wb_results,
        # Ozon поиск добавляется через /search команду отдельно
    }
