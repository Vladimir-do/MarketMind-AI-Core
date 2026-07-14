"""
universal.py — Универсальный парсер для обработки пустых или проблемных страниц.
Реализует поведение согласно задаче: не паниковать при пустом HTML,
а возвращать корректный ParseResult с предложением следующей стратегии.
"""
import re
from typing import Optional
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from app.parsers.base import BaseParser, ProductData
from app.config import logger


@dataclass
class ParseResult:
    """Результат парсинга, который может включать не только данные, но и мета-информацию."""
    success: bool
    data: Optional[ProductData] = None
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
        html_lower = html.lower()
        if "загрузка..." in html_lower or "loading" in html_lower or "<div>" not in html:
            return "EMPTY"
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
                import json
                ld = json.loads(script.string or "")
                if isinstance(ld, list):
                    ld = next((item for item in ld if item.get("@type") == "Product"), None)
                elif ld.get("@type") != "Product":
                    ld = None
                if ld:
                    name = ld.get("name")
                    description = ld.get("description")
                    img = ld.get("image")
                    if isinstance(img, list):
                        img = img[0] if img else None
                    image_url = img
                    offers = ld.get("offers")
                    if isinstance(offers, list):
                        offers = offers[0] if offers else None
                    if offers:
                        raw_price = offers.get("price") or offers.get("lowPrice")
                        if raw_price:
                            price = _parse_int_price(raw_price)
                        high = offers.get("highPrice")
                        if high:
                            old_price = _parse_int_price(high)
                        avail = (offers.get("availability") or "").lower()
                        if "instock" in avail or "in_stock" in avail:
                            availability = "in_stock"
                        elif "outofstock" in avail or "out_of_stock" in avail:
                            availability = "out_of_stock"
                        elif "discontinued" in avail:
                            availability = "deleted"
            except Exception:
                pass

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

        # ── 6. itemprop / class эвристики для изображения ────────────────────
        if not image_url:
            for selector in (
                '[itemprop="image"]',
                'img[class*="product"]',
                'div[class*="product"] img',
                'div[class*="gallery"] img',
                'main img',
                'article img',
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
    """Извлекает целое число цены из строки или числа."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    text = str(raw).strip()
    text = re.sub(r"[^\d.,]", "", text)
    text = text.replace(",", "")
    text = re.sub(r"\.(?=.*\d{3})", "", text)
    if not text:
        return None
    try:
        value = int(float(text))
        if 1 <= value <= 100_000_000:
            return value
    except (ValueError, OverflowError):
        pass
    return None
