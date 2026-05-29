"""
base.py — базовый класс парсера.
Каждый маркетплейс наследует его и реализует метод fetch_product().
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ProductData:
    """Унифицированная структура данных товара (любой маркетплейс)."""
    name: str
    price: int | None
    old_price: int | None
    discount_pct: int | None
    availability: str           # in_stock / out_of_stock / deleted
    url: str
    image_url: str | None
    # Расширенные поля
    rating: float | None = None
    reviews_count: int | None = None
    seller_name: str | None = None
    seller_rating: float | None = None
    brand: str | None = None
    category: str | None = None
    marketplace: str = "unknown"  # ozon / wildberries / aliexpress
    reviews: list[str] | None = None   # тексты отзывов для AI-анализа

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "price": self.price,
            "old_price": self.old_price,
            "discount_pct": self.discount_pct,
            "availability": self.availability,
            "image_url": self.image_url,
            "rating": self.rating,
            "reviews_count": self.reviews_count,
            "seller_name": self.seller_name,
            "seller_rating": self.seller_rating,
            "brand": self.brand,
            "category": self.category,
            "marketplace": self.marketplace,
            "reviews": self.reviews or [],
        }


class BaseParser(ABC):
    """Абстрактный базовый класс парсера маркетплейса."""

    @classmethod
    @abstractmethod
    def can_handle(cls, url: str) -> bool:
        """Возвращает True если этот парсер умеет обрабатывать данный URL."""
        ...

    @abstractmethod
    async def fetch_product(self, url: str) -> ProductData | None:
        """Загружает и парсит страницу товара. Возвращает ProductData или None."""
        ...

    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> list[ProductData]:
        """Ищет товары по названию."""
        ...
