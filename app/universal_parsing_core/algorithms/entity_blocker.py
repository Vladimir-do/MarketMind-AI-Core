from __future__ import annotations

from dataclasses import dataclass

from app.universal_parsing_core.algorithms.price_extractor import PriceCandidate


@dataclass(frozen=True)
class EntityBlock:
    text: str
    start: int
    end: int
    price: PriceCandidate


def extract_entity_blocks(text: str, prices: list[PriceCandidate], *, radius: int = 100) -> list[EntityBlock]:
    blocks: list[EntityBlock] = []
    for price in prices:
        start = max(0, price.start - radius)
        end = min(len(text), price.end + radius)

        left_breaks = [text.rfind(mark, 0, price.start) for mark in (".", "\n", "|", ";")]
        left = max([start, *left_breaks])
        if left > start:
            left += 1

        right_breaks = [text.find(mark, price.end, end) for mark in (".", "\n", "|", ";")]
        right_candidates = [candidate for candidate in right_breaks if candidate != -1]
        right = min(right_candidates) if right_candidates else end

        blocks.append(EntityBlock(text=text[left:right].strip(), start=left, end=right, price=price))
    return blocks
