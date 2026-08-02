"""Unified product schema for the Universal Import Layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class UnifiedProduct:
    """Canonical product representation shared across all import sources."""

    name: str
    source_id: str
    source_type: str

    description: str | None = None
    brand: str | None = None
    category: str | None = None
    sku: str | None = None

    price: int | None = None
    old_price: int | None = None
    discount_pct: int | None = None
    currency: str = "RUB"

    weight_g: int | None = None
    width_mm: int | None = None
    height_mm: int | None = None
    depth_mm: int | None = None

    image_urls: list[str] = field(default_factory=list)
    thumbnail_url: str | None = None

    attributes: dict[str, str] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    source_url: str | None = None
    marketplace: str | None = None
    availability: str = "in_stock"

    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "description": self.description,
            "brand": self.brand,
            "category": self.category,
            "sku": self.sku,
            "price": self.price,
            "old_price": self.old_price,
            "discount_pct": self.discount_pct,
            "currency": self.currency,
            "weight_g": self.weight_g,
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
            "depth_mm": self.depth_mm,
            "image_urls": self.image_urls,
            "thumbnail_url": self.thumbnail_url,
            "attributes": self.attributes,
            "tags": self.tags,
            "source_url": self.source_url,
            "marketplace": self.marketplace,
            "availability": self.availability,
        }

    def to_card_task(self) -> str:
        """Produce a text block consumable by build_ozon_card_draft()."""
        parts = [f"название: {self.name}"]
        if self.brand:
            parts.append(f"бренд: {self.brand}")
        if self.price is not None:
            parts.append(f"цена: {self.price} руб")
        if self.old_price is not None:
            parts.append(f"старая цена: {self.old_price} руб")
        if self.discount_pct is not None:
            parts.append(f"скидка: {self.discount_pct}%")
        if self.description:
            parts.append(f"описание: {self.description}")
        if self.category:
            parts.append(f"категория: {self.category}")
        if self.weight_g is not None:
            parts.append(f"вес: {self.weight_g} г")
        if self.width_mm is not None:
            parts.append(f"ширина: {self.width_mm} мм")
        if self.height_mm is not None:
            parts.append(f"высота: {self.height_mm} мм")
        if self.depth_mm is not None:
            parts.append(f"глубина: {self.depth_mm} мм")
        for url in self.image_urls:
            parts.append(f"фото: {url}")
        for key, val in self.attributes.items():
            parts.append(f"{key}: {val}")
        return "\n".join(parts)
