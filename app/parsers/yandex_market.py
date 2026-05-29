import json
import re
from time import perf_counter
from typing import Awaitable, Callable
from urllib.parse import quote_plus, urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from app.config import logger
from app.parsers.base import BaseParser, ProductData


AttemptRecorder = Callable[..., Awaitable[None]]

YANDEX_MARKET_HOSTS = (
    "market.yandex.ru",
    "market.yandex.by",
    "market.yandex.kz",
    "market.yandex.uz",
)


def is_yandex_market_url(url: str) -> bool:
    host = (urlparse(url or "").netloc or "").lower()
    return any(host == item or host.endswith("." + item) for item in YANDEX_MARKET_HOSTS)


def parse_yandex_market_html(html: str, url: str) -> ProductData | None:
    soup = BeautifulSoup(html or "", "lxml")
    page_text = soup.get_text(" ", strip=True).lower()

    json_ld_items = _json_ld_items(soup)
    product = _first_product_json_ld(json_ld_items)

    name = _json_value(product, "name") or _meta(soup, "og:title") or _h1(soup)
    name = _clean_name(name)
    if not name:
        return None

    offer = _json_value(product, "offers")
    price = _price_from_offer(offer) or _extract_price(page_text)
    old_price = None
    discount_pct = None
    availability = _availability_from_offer(offer, page_text, price)
    image_url = _image_from_json(product) or _meta(soup, "og:image")
    if image_url:
        image_url = urljoin(url, image_url)

    rating = _rating_from_json(product)
    reviews_count = _reviews_count_from_json(product)
    brand = _brand_from_json(product)
    category = _json_value(product, "category")

    return ProductData(
        name=name,
        price=price,
        old_price=old_price,
        discount_pct=discount_pct,
        availability=availability,
        url=url,
        image_url=image_url,
        rating=rating,
        reviews_count=reviews_count,
        brand=brand,
        category=category if isinstance(category, str) else None,
        marketplace="yandex_market",
    )


class YandexMarketParser(BaseParser):
    def __init__(self, attempt_recorder: AttemptRecorder | None = None):
        self._attempt_recorder = attempt_recorder

    @classmethod
    def can_handle(cls, url: str) -> bool:
        return is_yandex_market_url(url)

    async def _record_attempt(
        self,
        *,
        url: str,
        source: str,
        status: str,
        latency_ms: int,
        http_status: int | None = None,
        error: Exception | None = None,
    ) -> None:
        if not self._attempt_recorder:
            return
        try:
            await self._attempt_recorder(
                url=url,
                marketplace="yandex_market",
                source=source,
                status=status,
                latency_ms=latency_ms,
                http_status=http_status,
                error_class=type(error).__name__ if error else None,
                error_text=str(error) if error else None,
            )
        except Exception:
            pass

    async def fetch_product(self, url: str) -> ProductData | None:
        started = perf_counter()
        status_code = None
        try:
            async with aiohttp.ClientSession(headers=_headers(url)) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    status_code = response.status
                    html = await response.text(errors="replace")
            latency_ms = int((perf_counter() - started) * 1000)
            if status_code in {403, 429}:
                logger.warning(f"Yandex Market blocked: status={status_code} url={url}")
                await self._record_attempt(
                    url=url,
                    source="html",
                    status="blocked",
                    http_status=status_code,
                    latency_ms=latency_ms,
                )
                return None
            if status_code >= 400:
                await self._record_attempt(
                    url=url,
                    source="html",
                    status="http_error",
                    http_status=status_code,
                    latency_ms=latency_ms,
                )
                return None
            data = parse_yandex_market_html(html, url)
            if not data and _looks_blocked(html.lower()):
                await self._record_attempt(
                    url=url,
                    source="html",
                    status="blocked",
                    http_status=status_code,
                    latency_ms=latency_ms,
                )
                return None
            await self._record_attempt(
                url=url,
                source="html",
                status="ok" if data else "parse_error",
                http_status=status_code,
                latency_ms=latency_ms,
            )
            return data
        except Exception as exc:
            latency_ms = int((perf_counter() - started) * 1000)
            logger.warning(f"Yandex Market fetch error: {exc}")
            await self._record_attempt(
                url=url,
                source="html",
                status="error",
                http_status=status_code,
                latency_ms=latency_ms,
                error=exc,
            )
            return None

    async def search(self, query: str, max_results: int = 5) -> list[ProductData]:
        url = f"https://market.yandex.ru/search?text={quote_plus(query)}"
        data = await self.fetch_product(url)
        return [data] if data else []


def _headers(url: str) -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://market.yandex.ru/",
    }


def _json_ld_items(soup: BeautifulSoup) -> list[dict | list]:
    items = []
    for script in soup.select("script[type='application/ld+json']"):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        items.append(payload)
    return items


def _first_product_json_ld(items: list[dict | list]) -> dict:
    for item in _walk_json(items):
        if isinstance(item, dict) and str(item.get("@type", "")).lower() == "product":
            return item
    return {}


def _walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _json_value(payload, key: str):
    return payload.get(key) if isinstance(payload, dict) else None


def _meta(soup: BeautifulSoup, prop: str) -> str:
    node = soup.select_one(f"meta[property='{prop}']") or soup.select_one(f"meta[name='{prop}']")
    return str(node.get("content") or "").strip() if node else ""


def _h1(soup: BeautifulSoup) -> str:
    node = soup.select_one("h1")
    return node.get_text(" ", strip=True) if node else ""


def _clean_name(value: str | None) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    return re.sub(r"\s+[|:,-]\s+Яндекс Маркет.*$", "", value, flags=re.I)


def _price_from_offer(offer) -> int | None:
    if isinstance(offer, list):
        prices = [_price_from_offer(item) for item in offer]
        prices = [price for price in prices if price is not None]
        return min(prices) if prices else None
    if not isinstance(offer, dict):
        return None
    for key in ("price", "lowPrice", "highPrice"):
        value = offer.get(key)
        price = _int_price(value)
        if price:
            return price
    return None


def _extract_price(text: str) -> int | None:
    candidates = []
    for match in re.finditer(r"(\d[\d\s]{1,12})\s*(?:₽|руб)", text, flags=re.I):
        price = _int_price(match.group(1))
        if price and 10 <= price <= 50_000_000:
            candidates.append(price)
    return min(candidates) if candidates else None


def _int_price(value) -> int | None:
    raw = re.sub(r"[^\d]", "", str(value or ""))
    if not raw:
        return None
    price = int(raw)
    return price if price > 0 else None


def _availability_from_offer(offer, text: str, price: int | None) -> str:
    values = []
    if isinstance(offer, list):
        values = [str(item.get("availability", "")) for item in offer if isinstance(item, dict)]
    elif isinstance(offer, dict):
        values = [str(offer.get("availability", ""))]
    joined = " ".join(values).lower()
    if "outofstock" in joined or "soldout" in joined or "нет в продаже" in text:
        return "out_of_stock"
    if "instock" in joined or price:
        return "in_stock"
    return "out_of_stock"


def _image_from_json(product: dict) -> str | None:
    image = _json_value(product, "image")
    if isinstance(image, list) and image:
        return str(image[0])
    if isinstance(image, str):
        return image
    return None


def _rating_from_json(product: dict) -> float | None:
    rating = _json_value(product, "aggregateRating")
    value = _json_value(rating, "ratingValue")
    try:
        return float(str(value).replace(",", ".")) if value is not None else None
    except ValueError:
        return None


def _reviews_count_from_json(product: dict) -> int | None:
    rating = _json_value(product, "aggregateRating")
    for key in ("reviewCount", "ratingCount"):
        value = _int_price(_json_value(rating, key))
        if value is not None:
            return value
    return None


def _brand_from_json(product: dict) -> str | None:
    brand = _json_value(product, "brand")
    if isinstance(brand, dict):
        name = brand.get("name")
        return str(name).strip() if name else None
    if isinstance(brand, str):
        return brand.strip()
    return None


def _looks_blocked(text: str) -> bool:
    needles = (
        "captcha",
        "showcaptcha",
        "robot",
        "подтвердите, что запросы отправляли вы",
        "доступ ограничен",
    )
    return any(needle in text for needle in needles)
