"""
alt_sources.py — Альтернативные источники данных о товарах.

Используется когда основной парсинг Ozon заблокирован.
Получает данные через "чёрные ходы": кэш поисковиков, CDN, API-эндпоинты.
"""
import re
from urllib.parse import quote, urlparse

import aiohttp

from app.config import logger
from app.parsers.mcp_sources import fetch_product_via_mcp


_SERVICE_PAGE_TITLES = {
    "google search",
    "yandex search",
    "ozon search",
    "search",
    "search results",
    "google results",
    "results for",
}


def _looks_like_service_page_title(title: str | None) -> bool:
    normalized = re.sub(r"\s+", " ", (title or "").strip().lower())
    if not normalized:
        return True
    if normalized in _SERVICE_PAGE_TITLES:
        return True
    return any(marker in normalized for marker in ("search results", "google search", "yandex search"))


# ── Google Cache ─────────────────────────────────────────────────────────────

async def fetch_via_google_cache(url: str, timeout: float = 10.0) -> str | None:
    """Получает страницу из кэша Google."""
    cache_url = f"https://webcache.googleusercontent.com/search?q=cache:{quote(url)}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(cache_url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    if len(html) > 1000:
                        logger.info(f"Google cache hit: {url[:80]}")
                        return html
    except Exception as e:
        logger.debug(f"Google cache failed: {e}")
    return None


# ── Yandex Cache ─────────────────────────────────────────────────────────────

async def fetch_via_yandex_cache(url: str, timeout: float = 10.0) -> str | None:
    """Получает страницу из кэша Яндекса."""
    cache_url = f"https://yandexwebcache.net/yandbtm?fmode=inject&tm=1700000000&tld=ru&lang=ru&la=1700000000&text={quote(url)}&url={quote(url)}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(cache_url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    if len(html) > 1000:
                        logger.info(f"Yandex cache hit: {url[:80]}")
                        return html
    except Exception as e:
        logger.debug(f"Yandex cache failed: {e}")
    return None


# ── Ozon Search Suggestions API ──────────────────────────────────────────────

async def fetch_ozon_suggestions(query: str, timeout: float = 5.0) -> list[dict]:
    """Получает подсказки поиска Ozon — быстрый способ найти товар."""
    url = f"https://www.ozon.ru/api/serpbox/v2/search/suggest?text={quote(query)}&lang=ru"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("suggestions", [])
    except Exception as e:
        logger.debug(f"Ozon suggestions failed: {e}")
    return []


# ── Ozon Search API (мобильное API — обход антибота) ────────────────────────

async def fetch_ozon_search_api(query: str, timeout: float = 10.0) -> list[dict]:
    """Ищет товары через мобильное API Ozon — обход антибот-защиты."""
    import json as _json

    encoded_query = quote(query)
    url = (
        f"https://api.ozon.ru/composer-api.bx/page/json/v2"
        f"?url=%2Fsearch%2F%3Ftext%3D{encoded_query}"
        f"&layoutContainer=searchPageMobile&layoutVersion=2"
    )
    headers = {
        "User-Agent": "OzonApp/10.25.0 (Android 14)",
        "Accept": "application/json",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status != 200:
                    logger.debug(f"Ozon mobile API status {resp.status} for query={query!r}")
                    return []
                data = await resp.json()

                widgets = data.get("widgetStates", {})
                for key, value in widgets.items():
                    if "tile" not in key.lower() or not isinstance(value, str):
                        continue
                    try:
                        tile_data = _json.loads(value)
                    except Exception:
                        continue
                    items = tile_data.get("items", [])
                    if not items:
                        continue

                    results = []
                    for item in items:
                        product_id = item.get("id", "")
                        link = item.get("action", {}).get("link", "")
                        title = ""
                        price_text = ""
                        image_url = None

                        for state in item.get("mainState", []):
                            state_type = state.get("type", "")
                            if state_type == "title":
                                title = state.get("title", {}).get("text", "")
                            elif state_type == "priceV2":
                                prices = state.get("priceV2", {}).get("price", [])
                                if prices:
                                    price_text = prices[0].get("text", "")
                            elif state_type == "image":
                                img = state.get("image", {})
                                image_url = img.get("url") or img.get("imageUrl")

                        price = None
                        if price_text:
                            digits = re.sub(r"[^\d]", "", price_text)
                        price = int(digits) if digits else None

                        full_url = f"https://www.ozon.ru{link}" if link.startswith("/") else link
                        if _looks_like_service_page_title(title) and not price and not image_url:
                            continue

                        results.append({
                            "id": product_id,
                            "name": title or f"Товар Ozon {product_id}",
                            "price": price,
                            "url": full_url,
                            "image_url": image_url,
                        })

                    logger.info(f"Ozon mobile API: {len(results)} results for query={query!r}")
                    return results

    except Exception as e:
        logger.debug(f"Ozon mobile API failed: {e}")
    return []


# ── WB Suggestions API ──────────────────────────────────────────────────────

async def fetch_wb_suggestions(query: str, timeout: float = 5.0) -> list[dict]:
    """Получает подсказки поиска Wildberries."""
    url = f"https://search.wb.ru/exactmatch/ru/common/v5/suggest?ab_testing=false&appType=1&curr=rub&dest=-1257786&query={quote(query)}&spp=30"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("data", {}).get("products", [])
    except Exception as e:
        logger.debug(f"WB suggestions failed: {e}")
    return []


# ── Yandex Market Search ────────────────────────────────────────────────────

async def fetch_yandex_market_search(query: str, timeout: float = 10.0) -> str | None:
    """Ищет товар через Yandex Market (менее защищён чем Ozon)."""
    url = f"https://market.yandex.ru/search?text={quote(query)}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    if len(html) > 5000:
                        return html
    except Exception as e:
        logger.debug(f"Yandex Market search failed: {e}")
    return None


# ── Извлечение данных из HTML ───────────────────────────────────────────────

def extract_product_from_cache_html(html: str, url: str) -> dict | None:
    """Извлекает данные товара из кэшированного HTML."""
    if not html:
        return None
    
    result = {
        "url": url,
        "name": None,
        "price": None,
        "old_price": None,
        "availability": "unknown",
        "brand": None,
        "image_url": None,
    }
    
    # Извлекаем название из title
    title_match = re.search(r"<title>([^<]+)</title>", html, re.I)
    if title_match:
        title = title_match.group(1).strip()
        # Убираем "— Ozon" и подобное
        title = re.sub(r"\s*[-–—]\s*(Ozon|Wildberries|Яндекс Маркет).*$", "", title, flags=re.I)
        if _looks_like_service_page_title(title):
            title = ""
        result["name"] = title[:200]
    
    # Извлекаем цену из JSON-LD
    jsonld_match = re.search(r'"price"\s*:\s*"?(\d+)"?', html)
    if jsonld_match:
        result["price"] = int(jsonld_match.group(1))
    
    # Извлекаем бренд
    brand_match = re.search(r'"brand"\s*:\s*\{[^}]*"name"\s*:\s*"([^"]+)"', html)
    if brand_match:
        result["brand"] = brand_match.group(1)
    
    # Извлекаем картинку
    img_match = re.search(r'<meta[^>]*property="og:image"[^>]*content="([^"]+)"', html, re.I)
    if img_match:
        result["image_url"] = img_match.group(1)
    
    # Проверяем что извлекли хоть что-то
    if result["name"] or result["price"]:
        return result
    return None


# ── Основная функция ────────────────────────────────────────────────────────

async def fetch_from_alt_sources(url: str, query: str = "") -> dict | None:
    """
    Пробует получить данные товара из альтернативных источников.
    Возвращает dict с данными товара или None.
    """
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    
    # Для Ozon пробуем кэш и API
    if "ozon.ru" in host:
        # 1. Пробуем внешний MCP-источник, если он явно включен.
        mcp_data = await fetch_product_via_mcp(url, marketplace="ozon")
        if mcp_data:
            return mcp_data

        # 2. Пробуем Ozon Search API
        if query:
            items = await fetch_ozon_search_api(query)
            if items:
                item = items[0] if isinstance(items, list) else items
                return {
                    "url": url,
                    "name": item.get("title") or item.get("name"),
                    "price": item.get("price") or item.get("priceU"),
                    "availability": "in_stock" if item.get("price") or item.get("priceU") else "unknown",
                    "brand": item.get("brand"),
                    "image_url": item.get("image"),
                }
        
        # 3. Пробуем Google Cache
        html = await fetch_via_google_cache(url)
        if html:
            return extract_product_from_cache_html(html, url)
        
        # 4. Пробуем Yandex Cache
        html = await fetch_via_yandex_cache(url)
        if html:
            return extract_product_from_cache_html(html, url)
    
    # Для WB — WB API уже надёжный, но пробуем suggestions
    elif "wildberries.ru" in host or "wb.ru" in host:
        if query:
            items = await fetch_wb_suggestions(query)
            if items:
                item = items[0]
                return {
                    "url": f"https://www.wildberries.ru/catalog/{item.get('id')}/detail.aspx",
                    "name": item.get("name"),
                    "price": item.get("sizes", [{}])[0].get("price", {}).get("product") if item.get("sizes") else None,
                    "availability": "in_stock",
                    "brand": item.get("brand"),
                    "image_url": None,
                }
    
    return None
