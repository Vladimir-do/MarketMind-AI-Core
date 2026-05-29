from __future__ import annotations

from app.universal_parsing_core.schemas.normalized_entity import NormalizedEntity


def validate_entities(entities: list[NormalizedEntity]) -> tuple[list[NormalizedEntity], list[str]]:
    valid: list[NormalizedEntity] = []
    warnings: list[str] = []
    seen: set[tuple[str, float | None]] = set()

    for entity in entities:
        if not entity.title:
            warnings.append("Entity skipped: empty title")
            continue
        if entity.price is None:
            warnings.append(f"Entity skipped: missing price for {entity.title}")
            continue
        key = (entity.title.lower(), entity.price)
        if key in seen:
            continue
        seen.add(key)
        valid.append(entity)

    return valid, warnings
