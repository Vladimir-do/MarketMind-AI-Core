from __future__ import annotations

import re

from app.universal_parsing_core.algorithms.entity_blocker import EntityBlock


TRAILING_META_RE = re.compile(r"\b\d+\s*(г|гр|kg|кг|мл|л|шт)\b.*$", re.IGNORECASE)
LEADING_NOISE_RE = re.compile(r"^(меню|цена|стоимость|от)\s+", re.IGNORECASE)


def match_title_near_price(block: EntityBlock) -> str:
    relative_price_start = max(0, block.price.start - block.start)
    before_price = block.text[:relative_price_start]
    before_price = re.sub(r"\s+", " ", before_price).strip(" :-–—")
    before_price = LEADING_NOISE_RE.sub("", before_price).strip()
    before_price = TRAILING_META_RE.sub("", before_price).strip()

    if before_price:
        words = before_price.split()
        return " ".join(words[-8:])

    after_price = block.text[relative_price_start:].strip(" :-–—")
    words = after_price.split()
    return " ".join(words[:8])
