"""
universal.py — Универсальный парсер для обработки пустых или проблемных страниц.
Реализует поведение согласно задаче: не паниковать при пустом HTML,
а возвращать корректный ParseResult с предложением следующей стратегии.
"""

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from bs4 import BeautifulSoup

from app.parsers.base import BaseParser, ProductData


@dataclass
class ParseResult:
    """Результат парсинга, который может включать не только данные, но и мета-информацию."""

    success: bool
    data: ProductData | None = None
    page_structure: str = "unknown"
    warnings: list[str] = None
    next_strategy: str = "none"

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class UniversalParser(BaseParser):
    """Универсальный парсер для обработки произвольных HTML-страниц.

    Пытается извлечь название, цену, описание, изображение и наличие
    из любой HTML-страницы, используя эвристики по мета-тегам и
    микроразметке (Schema.org JSON-LD / itemprop).
    """

    @classmethod
    def can_handle(cls, url: str) -> bool:
        """Этот парсер может обработать любой URL."""
        return True

    def _detect_page_structure(self, html: str) -> str:
        """Определяет структуру страницы на основе HTML."""
        if not html or not html.strip():
            return "EMPTY"

        soup = BeautifulSoup(html, "lxml")
        visible_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).casefold()
        if not visible_text or visible_text in {"loading", "loading...", "загрузка", "загрузка..."}:
            return "EMPTY"

        html_lower = html.lower()
        if "product" in html_lower and ("price" in html_lower or "цена" in html_lower):
            return "PRODUCT"
        if "catalog" in html_lower or "category" in html_lower:
            return "CATALOG"
        return "unknown"

    async def fetch_product(self, url: str, html: str = "<html><body></body></html>") -> ParseResult:
        """Парсит HTML и возвращает ParseResult.

        Извлекает данные товара через JSON-LD (Schema.org), Open Graph,
        itemprop-атрибуты и общие эвристики.

        Args:
            url: URL страницы.
            html: Строка с HTML-контентом страницы.

        Returns:
            ParseResult с результатом и рекомендацией по следующей стратегии.
        """
        page_structure = self._detect_page_structure(html)

        if page_structure == "EMPTY":
            return ParseResult(
                success=False,
                data=None,
                page_structure=page_structure,
                warnings=["no entities found"],
                next_strategy="browser",
            )

        soup = BeautifulSoup(html, "lxml")
        warnings: list[str] = []
        name: str | None = None
        price: int | None = None
        old_price: int | None = None
        description: str | None = None
        image_url: str | None = None
        availability: str = "unknown"

        # ── 1. JSON-LD (Schema.org Product) ──────────────────────────────────
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                payload = json.loads(script.string or script.get_text() or "")
            except (json.JSONDecodeError, TypeError):
                continue

            if isinstance(payload, dict):
                candidates = payload.get("@graph", [])
                if not isinstance(candidates, list):
                    candidates = []
                candidates = [payload, *candidates]
            elif isinstance(payload, list):
                candidates = payload
            else:
                candidates = []

            for ld in candidates:
                if not isinstance(ld, dict):
                    continue
                product_types = ld.get("@type", [])
                if isinstance(product_types, str):
                    product_types = [product_types]
                if not isinstance(product_types, list) or "Product" not in product_types:
                    continue

                name = ld.get("name") or name
                description = ld.get("description") or description
                img = ld.get("image")
                if isinstance(img, list):
                    img = img[0] if img else None
                if isinstance(img, dict):
                    img = img.get("url") or img.get("contentUrl")
                if isinstance(img, str):
                    image_url = img

                offers = ld.get("offers")
                if isinstance(offers, list):
                    offers = next((offer for offer in offers if isinstance(offer, dict)), None)
                if isinstance(offers, dict):
                    raw_price = offers.get("price") or offers.get("lowPrice")
                    if raw_price is not None:
                        price = _parse_int_price(raw_price)
                    high = offers.get("highPrice")
                    if high is not None:
                        old_price = _parse_int_price(high)
                    avail = str(offers.get("availability") or "").lower()
                    if "instock" in avail or "in_stock" in avail:
                        availability = "in_stock"
                    elif "outofstock" in avail or "out_of_stock" in avail:
                        availability = "out_of_stock"
                    elif "discontinued" in avail:
                        availability = "deleted"
                if name or price is not None:
                    break
            if name or price is not None:
                break

        # ── 2. Open Graph ────────────────────────────────────────────────────
        if not name:
            og = soup.find("meta", property="og:title")
            if og:
                name = og.get("content")
        if not image_url:
            og_img = soup.find("meta", property="og:image")
            if og_img:
                image_url = og_img.get("content")
        if not description:
            og_desc = soup.find("meta", property="og:description")
            if og_desc:
                description = og_desc.get("content")

        # ── 3. Meta description ──────────────────────────────────────────────
        if not description:
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc:
                description = meta_desc.get("content")

        # ── 4. itemprop / class эвристики для названия ────────────────────────
        if not name:
            for selector in (
                '[itemprop="name"]',
                "h1",
                'h1[class*="title"]',
                'h2[class*="title"]',
                'div[class*="product-name"]',
                'div[class*="product_title"]',
                'div[class*="product-name"]',
                'span[class*="product-name"]',
            ):
                elem = soup.select_one(selector)
                if elem:
                    name = elem.get_text(strip=True)
                    if name:
                        break

        # ── 5. itemprop / class эвристики для цены ───────────────────────────
        if price is None:
            for selector in (
                '[itemprop="price"]',
                'span[class*="price"]',
                'div[class*="price"]',
                'span[class*="Price"]',
                'div[class*="Price"]',
                'meta[itemprop="price"]',
            ):
                for elem in soup.select(selector):
                    content = elem.get("content") or elem.get_text(strip=True)
                    parsed = _parse_int_price(content)
                    if parsed and 1 < parsed < 100_000_000:
                        price = parsed
                        break
                if price is not None:
                    break

        # ── 5a. Цена в видимом тексте с явной меткой ───────────────────────
        if price is None:
            visible_text = soup.get_text(" ", strip=True)
            price_match = re.search(
                r"(?:цена|price)\\s*[:：]?\\s*([\\d\\s\\u00a0.,]+)",
                visible_text,
                flags=re.IGNORECASE,
            )
            if price_match:
                parsed = _parse_int_price(price_match.group(1))
                if parsed and 1 < parsed < 100_000_000:
                    price = parsed

        # ── 6. itemprop / class эвристики для изображения ────────────────────
        if not image_url:
            for selector in (
                '[itemprop="image"]',
                'img[class*="product"]',
                'div[class*="product"] img',
                'div[class*="gallery"] img',
                "main img",
                "article img",
            ):
                img = soup.select_one(selector)
                if img:
                    src = img.get("src") or img.get("data-src") or ""
                    if src and src.startswith("http"):
                        image_url = src
                        break

        # ── 7. itemprop для availability ─────────────────────────────────────
        if availability == "unknown":
            avail_elem = soup.find(attrs={"itemprop": "availability"})
            if avail_elem:
                href = avail_elem.get("href", "").lower()
                text = (avail_elem.get("content") or avail_elem.get_text()).lower()
                if "instock" in href or "instock" in text or "в наличии" in text:
                    availability = "in_stock"
                elif "outofstock" in href or "outofstock" in text or "нет в наличии" in text:
                    availability = "out_of_stock"

        # ── 8. Если нашли хотя бы название — считаем успех ──────────────────
        if name and len(name) >= 2:
            return ParseResult(
                success=True,
                data=ProductData(
                    name=name[:500],
                    price=price,
                    old_price=old_price,
                    discount_pct=(
                        round((old_price - price) / old_price * 100)
                        if price and old_price and old_price > price
                        else None
                    ),
                    availability=availability,
                    url=url,
                    image_url=image_url,
                    marketplace="unknown",
                ),
                page_structure=page_structure,
                warnings=warnings,
                next_strategy="none",
            )

        # ── 9. Не удалось извлечь название ───────────────────────────────────
        warnings.append("product name not found")
        return ParseResult(
            success=False,
            data=None,
            page_structure=page_structure,
            warnings=warnings,
            next_strategy="browser",
        )

    async def search(self, query: str, max_results: int = 5) -> list[ProductData]:
        """Поиск не поддерживается универсальным парсером."""
        return []


def _parse_int_price(raw) -> int | None:
    """Извлекает целую цену, корректно обрабатывая RU/EU/US разделители."""
    if raw is None:
        return None
    try:
        if isinstance(raw, (int, float, Decimal)):
            value = int(Decimal(str(raw)))
        else:
            text = re.sub(r"[^\d.,]", "", str(raw).replace(" ", "").replace("\u00a0", ""))
            if not text:
                return None

            dot = text.rfind(".")
            comma = text.rfind(",")
            if dot >= 0 and comma >= 0:
                decimal_separator = "." if dot > comma else ","
                thousands_separator = "," if decimal_separator == "." else "."
                decimals = len(text) - max(dot, comma) - 1
                if 1 <= decimals <= 2:
                    text = text.replace(thousands_separator, "")
                    if decimal_separator == ",":
                        text = text.replace(",", ".")
                else:
                    text = text.replace(".", "").replace(",", "")
            elif dot >= 0 or comma >= 0:
                separator = "." if dot >= 0 else ","
                decimals = len(text) - text.rfind(separator) - 1
                text = (
                    text.replace(",", ".")
                    if decimals in (1, 2)
                    else text.replace(".", "").replace(",", "")
                )

            value = int(Decimal(text))
        if 1 <= value <= 100_000_000:
            return value
    except (InvalidOperation, ValueError, OverflowError):
        pass
    return None
