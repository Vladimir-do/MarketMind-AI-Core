"""Marketplace search helpers for project market analysis."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from app.parsers.router import search_all_marketplaces
from app.parsers.wildberries import WildberriesParser
from app.searcher import ozon_search_blocked_message

if TYPE_CHECKING:
    from app.parsers.base import ProductData

SUPPORTED_MARKET_ANALYSIS_MARKETPLACES = {"wildberries", "ozon", "yandex_market", "all"}
TOO_BROAD_MARKET_ANALYSIS_QUERIES = {
    "all",
    "any",
    "все",
    "всё",
    "товары",
    "товар",
    "каталог",
    "любой",
    "любые",
}
MARKET_ANALYSIS_STOP_WORDS = {
    "для",
    "или",
    "что",
    "как",
    "чем",
    "где",
    "при",
    "без",
    "под",
    "над",
    "это",
    "товар",
    "товары",
    "рынок",
    "ниша",
    "нишу",
    "продажи",
}


@dataclass(frozen=True)
class MarketAnalysisResult:
    query: str
    marketplace: str
    products: list[ProductData]
    executed_queries: list[str] = field(default_factory=list)
    ozon_blocked_message: str | None = None

    @property
    def found_count(self) -> int:
        return len(self.products)


def normalize_marketplace(value: str | None) -> str:
    normalized = (value or "wildberries").strip().lower()
    aliases = {
        "wb": "wildberries",
        "wildberries": "wildberries",
        "wildberries.ru": "wildberries",
        "озон": "ozon",
        "ozon": "ozon",
        "ozon.ru": "ozon",
        "ym": "yandex_market",
        "yandex": "yandex_market",
        "yandex_market": "yandex_market",
        "market.yandex": "yandex_market",
        "all": "all",
        "any": "all",
        "все": "all",
    }
    return aliases.get(normalized, normalized)


def market_analysis_filename(query: str, marketplace: str) -> str:
    safe_query = re.sub(r"[^a-zA-Zа-яА-Я0-9_-]+", "_", query.strip(), flags=re.UNICODE).strip("_")
    safe_marketplace = re.sub(r"[^a-z0-9_-]+", "_", marketplace.lower()).strip("_")
    return f"market_analysis_{safe_marketplace}_{safe_query or 'query'}.csv"


async def run_market_analysis(query: str, *, marketplace: str = "wildberries", max_results: int = 12) -> MarketAnalysisResult:
    normalized_query = re.sub(r"\s+", " ", (query or "").strip())
    if not normalized_query:
        raise ValueError("Укажите поисковый запрос для анализа рынка")

    if needs_ai_query_expansion(normalized_query):
        search_queries = await generate_search_queries_with_ai(normalized_query, marketplace)
    else:
        search_queries = normalize_market_analysis_queries(normalized_query)

    if not search_queries:
        raise ValueError(
            "Не удалось сгенерировать поисковые запросы. "
            "Попробуйте переформулировать, например: кабель менеджмент, органайзер для проводов"
        )

    normalized_marketplace = normalize_marketplace(marketplace)
    if normalized_marketplace not in SUPPORTED_MARKET_ANALYSIS_MARKETPLACES:
        raise ValueError("Анализ рынка сейчас поддерживает Wildberries, Ozon, Яндекс Маркет или все источники")

    bounded_limit = max(1, min(int(max_results or 12), 30))
    per_query_limit = max(1, min(bounded_limit, max(1, bounded_limit // len(search_queries))))
    products: list[ProductData] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    for search_query in search_queries:
        found = await _search_marketplace(search_query, normalized_marketplace, max_results=per_query_limit)
        for product in found:
            if product.url in seen_urls:
                continue
            title_key = _normalize_title_key(product.name)
            if title_key and title_key in seen_titles:
                continue
            if not product_matches_market_query(product, search_query):
                continue
            seen_urls.add(product.url)
            if title_key:
                seen_titles.add(title_key)
            if not product.category:
                product.category = search_query
            products.append(product)
            if len(products) >= bounded_limit:
                break
        if len(products) >= bounded_limit:
            break

    ozon_message = ozon_search_blocked_message() if normalized_marketplace in ("ozon", "all") else None

    return MarketAnalysisResult(
        query=normalized_query,
        marketplace=normalized_marketplace,
        products=products,
        executed_queries=search_queries,
        ozon_blocked_message=ozon_message,
    )


def normalize_market_analysis_queries(raw_query: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", (raw_query or "").strip(" \t\r\n.,;:!?-–—"))
    if not normalized:
        return []
    low = normalized.lower()
    if low in TOO_BROAD_MARKET_ANALYSIS_QUERIES:
        return []

    concrete = _extract_concrete_query(normalized)
    if concrete and concrete.lower() not in TOO_BROAD_MARKET_ANALYSIS_QUERIES:
        return [concrete]

    return [normalized]


def needs_ai_query_expansion(raw_query: str) -> bool:
    """Проверяет, нужна ли AI-генерация поисковых запросов."""
    normalized = re.sub(r"\s+", " ", (raw_query or "").strip(" \t\r\n.,;:!?-–—")).lower()
    if not normalized:
        return False
    if normalized in TOO_BROAD_MARKET_ANALYSIS_QUERIES:
        return False
    return _looks_like_open_ended_niche_task(normalized)


async def generate_search_queries_with_ai(raw_query: str, marketplace: str) -> list[str]:
    """Использует AI для генерации конкретных поисковых запросов из свободного текста."""
    from app.ai_client import AIClientError, ask_ai

    marketplace_names = {
        "wildberries": "Wildberries",
        "ozon": "Ozon",
        "yandex_market": "Яндекс Маркет",
        "all": "маркетплейсах (Wildberries, Ozon, Яндекс Маркет)",
    }
    mp_name = marketplace_names.get(marketplace, marketplace)

    prompt = (
        f"Пользователь хочет найти товары для продажи на {mp_name}. "
        f"Его запрос: \"{raw_query}\"\n\n"
        f"Сгенерируй ровно 5 конкретных поисковых запросов для поиска товаров на {mp_name}. "
        "Запросы должны быть:\n"
        "- на русском языке\n"
        "- конкретными (название товара или категории)\n"
        "- разными (не повторяться)\n"
        "- пригодными для поиска на маркетплейсе\n\n"
        "Верни ТОЛЬКО JSON-массив строк, без пояснений. Пример:\n"
        '[\"органайзер для проводов\", \"кабель менеджмент\", \"клипса для кабеля\"]'
    )

    try:
        try:
            response = await ask_ai(prompt, max_tokens=300)
        except AIClientError:
            return []
        cleaned = response.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [line for line in lines if not line.strip().startswith("```")]
            cleaned = "\n".join(lines).strip()
        queries = json.loads(cleaned)
        if isinstance(queries, list) and all(isinstance(q, str) and q.strip() for q in queries):
            return [q.strip() for q in queries if q.strip()][:5]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _looks_like_open_ended_niche_task(low: str) -> bool:
    commercial_markers = ("чем торг", "что продав", "прибыл", "выгод", "маржин", "ниша")
    task_markers = ("ищ", "подбер", "най", "рын", "ниш", "торг", "продав", "для продаж")
    return any(marker in low for marker in commercial_markers) and any(marker in low for marker in task_markers)


async def _search_marketplace(query: str, marketplace: str, *, max_results: int) -> list[ProductData]:
    if marketplace == "wildberries":
        return await WildberriesParser().search(query, max_results=max_results)
    exclusions = tuple(
        name
        for name in ("wildberries", "ozon", "yandex_market")
        if marketplace != "all" and name != marketplace
    )
    grouped = await search_all_marketplaces(
        query,
        max_per_site=max_results if marketplace != "all" else max(1, max_results // 3),
        exclude_marketplaces=exclusions,
    )
    return [product for items in grouped.values() for product in items][:max_results]


def _extract_concrete_query(text: str) -> str | None:
    patterns = [
        r"(?:по|для|про|на тему|товар[:\s]+|ниша[:\s]+)\s+(.+)$",
        r"^(?:найди|найти|поищи|ищи|проанализируй|анализируй|посмотри|изучи)\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if not match:
            continue
        candidate = _strip_task_words(match.group(1))
        if _is_specific_query(candidate):
            return candidate
    stripped = _strip_task_words(text)
    return stripped if _is_specific_query(stripped) else None


def _strip_task_words(text: str) -> str:
    cleaned = re.sub(
        r"\b(?:сегодня|сейчас|давай|мы|я|мне|нам|рынок|на рынке|анализ|анализ рынка|ищем|искать|найти|найди|прибыльнее|прибыльней|выгоднее|выгодней|выгодно|выгодный|прибыльную|прибыльный|маржинальную|нишу|ниша|торговать|чем торговать|что продавать)\b",
        " ",
        text,
        flags=re.I,
    )
    return re.sub(r"\s+", " ", cleaned).strip(" \t\r\n.,;:!?-–—")


def _is_specific_query(text: str | None) -> bool:
    if not text:
        return False
    low = text.lower()
    if low in TOO_BROAD_MARKET_ANALYSIS_QUERIES:
        return False
    tokens = re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9]+", low)
    return len(tokens) >= 2 or any(len(token) >= 6 for token in tokens)


def product_matches_market_query(product: ProductData, query: str) -> bool:
    query_tokens = _meaningful_token_keys(query)
    if not query_tokens:
        return False
    product_tokens = _meaningful_token_keys(" ".join([
        product.name or "",
        product.brand or "",
        product.category or "",
    ]))
    return bool(query_tokens & product_tokens)


def _meaningful_token_keys(text: str) -> set[str]:
    tokens = re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9]+", (text or "").lower())
    result = set()
    for token in tokens:
        if token in MARKET_ANALYSIS_STOP_WORDS or len(token) < 4:
            continue
        result.add(_token_key(token))
    return result


def _token_key(token: str) -> str:
    return token[:5] if re.search(r"[а-яё]", token, flags=re.I) else token[:6]


def _normalize_title_key(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def market_analysis_products_to_rows(result: MarketAnalysisResult) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for index, product in enumerate(result.products, start=1):
        product_query = product.category or result.query
        rows.append(
            {
                "Название": product.name or f"Товар {index}",
                "Описание": _analysis_description(product_query, product),
                "Бренд": product.brand or "NoBrand",
                "Категория": product_query,
                "Артикул": _marketplace_sku(product),
                "Цена": "" if product.price is None else str(product.price),
                "Старая цена": "" if product.old_price is None else str(product.old_price),
                "Остаток / наличие": product.availability or "unknown",
                "Маркетплейс": product.marketplace or result.marketplace,
                "URL": product.url,
                "Изображения": product.image_url or "",
                "Дополнительная характеристика": _analysis_attributes(product_query, product),
            }
        )
    return rows


def _marketplace_sku(product: ProductData) -> str:
    if product.marketplace == "wildberries":
        match = re.search(r"/catalog/(\d{6,12})(?:/|$)", urlparse(product.url).path)
        if match:
            return match.group(1)
    return ""


def _analysis_description(query: str, product: ProductData) -> str:
    name = product.name or "Товар"
    return (
        f"{name}. Товар из ниши {query}. "
        "Используйте эту карточку как конкурентный пример для оценки ассортимента, визуала и позиционирования."
    )


def _analysis_attributes(query: str, product: ProductData) -> str:
    attrs = [
        "source=market_analysis",
        f"query={query}",
        f"marketplace={product.marketplace}",
    ]
    if product.rating is not None:
        attrs.append(f"rating={product.rating}")
    if product.reviews_count is not None:
        attrs.append(f"reviews_count={product.reviews_count}")
    if product.price is not None:
        attrs.append(f"price={product.price}")
    if product.old_price is not None:
        attrs.append(f"old_price={product.old_price}")
    if product.discount_pct is not None:
        attrs.append(f"discount_pct={product.discount_pct}")
    if product.seller_name:
        attrs.append(f"seller={product.seller_name}")
    return "; ".join(attrs)
