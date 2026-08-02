"""Bridge between UnifiedProduct and existing project types (ProductData, card tasks)."""

from __future__ import annotations

from app.parsers.base import ProductData
from app.products.schema import UnifiedProduct


def unified_to_product_data(product: UnifiedProduct) -> ProductData:
    """Convert a UnifiedProduct to ProductData for the parsers pipeline."""
    return ProductData(
        name=product.name,
        price=product.price,
        old_price=product.old_price,
        discount_pct=product.discount_pct,
        availability=product.availability or "in_stock",
        url=product.source_url or "",
        image_url=product.thumbnail_url or (product.image_urls[0] if product.image_urls else None),
        brand=product.brand,
        category=product.category,
        marketplace=product.marketplace or "unknown",
    )


def unified_to_card_task(product: UnifiedProduct) -> str:
    """Produce a text block consumable by build_ozon_card_draft()."""
    return product.to_card_task()


def unified_to_dict(product: UnifiedProduct) -> dict:
    """Convert to a plain dict suitable for Database.save_product()."""
    return product.to_dict()
