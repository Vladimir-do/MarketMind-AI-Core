from __future__ import annotations

from app.universal_parsing_core.schemas.normalized_entity import NormalizedEntity
from app.universal_parsing_core.schemas.page_structure import PageStructure


def calculate_confidence(
    entities: list[NormalizedEntity],
    *,
    page_structure: PageStructure,
    has_title: bool,
    structure_signals: object | None = None,
) -> float:
    if not entities:
        if page_structure is PageStructure.CATALOG and _strong_catalog_signals(structure_signals):
            return 0.88 if has_title else 0.85
        if page_structure in {PageStructure.CATALOG, PageStructure.SINGLE, PageStructure.ARTICLE} and has_title:
            return 0.55
        return 0.2

    complete_entities = [
        entity for entity in entities
        if entity.title
        and entity.price is not None
        and bool(entity.url)
        and entity.attributes.get("url_source") == "detail_link"
        and not bool(entity.attributes.get("title_is_price_only"))
    ]
    title_price_entities = [
        entity for entity in entities
        if entity.title
        and entity.price is not None
        and not bool(entity.attributes.get("title_is_price_only"))
    ]
    price_only_entities = [
        entity for entity in entities
        if entity.price is not None
        and (not entity.title or bool(entity.attributes.get("title_is_price_only")))
    ]

    if complete_entities:
        score = 0.85
        if len(complete_entities) > 1:
            score += 0.05
        return min(1.0, score)
    if title_price_entities:
        score = 0.75
        if len(title_price_entities) > 1:
            score += 0.05
        return min(1.0, score)
    if price_only_entities:
        return 0.3

    score = 0.35
    if has_title:
        score += 0.1
    if page_structure in {PageStructure.SINGLE, PageStructure.CATALOG, PageStructure.MIXED, PageStructure.ARTICLE}:
        score += 0.1
    if all(entity.title and entity.price is not None for entity in entities):
        score += 0.25
    if any(entity.entity_type != "generic" for entity in entities):
        score += 0.1
    if len(entities) > 1:
        score += 0.05
    return score


def _strong_catalog_signals(signals: object | None) -> bool:
    if signals is None:
        return False
    product_pods = int(getattr(signals, "product_pod_count", 0) or 0)
    card_like = int(getattr(signals, "card_like_count", 0) or 0)
    detail_links = int(getattr(signals, "detail_link_count", 0) or 0)
    prices = int(getattr(signals, "price_count", 0) or 0)
    has_pagination = bool(getattr(signals, "has_pagination", False))
    return (
        product_pods >= 3
        or (card_like >= 3 and detail_links >= 3)
        or (detail_links >= 3 and (prices >= 2 or has_pagination))
    )
