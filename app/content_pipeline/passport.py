"""Адаптер EffectiveProductCard -> ProductPassport."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.content_pipeline.schemas import ProductPassport
from app.products.schema import UnifiedProduct

if TYPE_CHECKING:
    from app.effective_card.service import EffectiveProductCard


def build_passport(card: EffectiveProductCard) -> ProductPassport:
    """Строит Product Passport из эффективного снапшота карточки.

    ProductPassport — единственный источник истины, на который опираются
    все стадии пайплайна (в первую очередь Fact Checker).
    """
    snapshot = card.effective_snapshot
    tags = snapshot.get("tags") or []
    if isinstance(tags, str):
        tags = [item.strip() for item in tags.replace(";", ",").split(",") if item.strip()]

    return ProductPassport(
        product_id=card.product_id,
        project_id=card.project_id,
        project_product_id=card.project_product_id,
        title=str(snapshot.get("title") or ""),
        description=snapshot.get("description"),
        brand=snapshot.get("brand"),
        category=snapshot.get("category"),
        sku=snapshot.get("sku") or snapshot.get("external_product_id"),
        marketplace=str(snapshot.get("marketplace") or "unknown"),
        price=snapshot.get("price"),
        attributes={
            str(k): str(v) for k, v in (snapshot.get("attributes") or {}).items() if not str(k).startswith("source:")
        },
        tags=[str(t) for t in tags],
        image_urls=list(snapshot.get("image_urls") or []),
        weight_g=snapshot.get("weight_g"),
        width_mm=snapshot.get("width_mm"),
        height_mm=snapshot.get("height_mm"),
        depth_mm=snapshot.get("depth_mm"),
        source_url=snapshot.get("source_url"),
    )


def passport_to_unified(
    passport: ProductPassport,
    *,
    title: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
) -> UnifiedProduct:
    """Строит UnifiedProduct для SEO-аудита черновика (title/description могут
    быть промежуточным результатом стадий Title/Description Generator,
    а не финальным значением из паспорта)."""
    return UnifiedProduct(
        name=title if title is not None else passport.title,
        source_id=passport.sku or str(passport.product_id),
        source_type=passport.marketplace,
        description=description if description is not None else passport.description,
        brand=passport.brand,
        category=passport.category,
        sku=passport.sku,
        price=passport.price,
        weight_g=passport.weight_g,
        width_mm=passport.width_mm,
        height_mm=passport.height_mm,
        depth_mm=passport.depth_mm,
        image_urls=list(passport.image_urls),
        attributes=dict(passport.attributes),
        tags=tags if tags is not None else list(passport.tags),
        source_url=passport.source_url,
        marketplace=passport.marketplace,
    )
