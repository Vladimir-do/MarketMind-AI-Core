"""Профили SEO-правил для маркетплейсов."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SEOMarketplaceRule:
    """Набор SEO-ограничений для конкретного маркетплейса."""

    marketplace_name: str
    title_max: int = 140
    title_min: int = 25
    description_min: int = 350
    min_keywords: int = 6
    min_attributes: int = 4
    min_images: int = 3
    forbidden_words: frozenset[str] = field(default_factory=lambda: frozenset({
        "лучший", "топ", "скидка", "акция", "купить", "дешево", "недорого", "гарантируем",
    }))
    required_fields: frozenset[str] = field(default_factory=lambda: frozenset({
        "name", "description", "price", "images",
    }))


MARKETPLACE_RULES: dict[str, SEOMarketplaceRule] = {
    "universal": SEOMarketplaceRule(
        marketplace_name="universal",
        title_max=140,
        title_min=25,
        description_min=350,
        min_keywords=6,
        min_attributes=4,
        min_images=3,
    ),
    "ozon": SEOMarketplaceRule(
        marketplace_name="ozon",
        title_max=150,
        title_min=25,
        description_min=500,
        min_keywords=8,
        min_attributes=5,
        min_images=3,
    ),
    "wildberries": SEOMarketplaceRule(
        marketplace_name="wildberries",
        title_max=60,
        title_min=25,
        description_min=300,
        min_keywords=6,
        min_attributes=4,
        min_images=3,
    ),
    "yandex_market": SEOMarketplaceRule(
        marketplace_name="yandex_market",
        title_max=30,
        title_min=25,
        description_min=200,
        min_keywords=5,
        min_attributes=3,
        min_images=1,
    ),
    "avito": SEOMarketplaceRule(
        marketplace_name="avito",
        title_max=50,
        title_min=25,
        description_min=100,
        min_keywords=0,
        min_attributes=0,
        min_images=1,
    ),
}


def get_marketplace_rules(marketplace: str) -> SEOMarketplaceRule:
    """Вернуть правила для маркетплейса. Для неизвестного -- universal."""
    return MARKETPLACE_RULES.get(marketplace.lower().strip(), MARKETPLACE_RULES["universal"])
