from __future__ import annotations

import re
from dataclasses import dataclass


PRICE_RE = re.compile(
    r"(?:([£$€])\s*)?(\d[\d\s]{0,12}(?:[.,]\d{1,2})?)\s*(₽|руб\.?|р\.?|р|в‚Ѕ|СЂСѓР±\.?|СЂ\.?|СЂ|£|gbp|usd|eur)?(?=\s|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PriceCandidate:
    value: float
    raw: str
    currency: str
    start: int
    end: int


def extract_price_candidates(text: str) -> list[PriceCandidate]:
    text = (text or "").replace("\u00c2\u00a3", "£").replace("\u0412\u0408", "£")
    candidates: list[PriceCandidate] = []
    for match in PRICE_RE.finditer(text):
        leading_currency = match.group(1) or ""
        raw_number = match.group(2).replace(" ", "").replace(",", ".")
        trailing_currency = match.group(3) or ""
        if not leading_currency and not trailing_currency:
            continue
        if not re.fullmatch(r"\d+(?:\.\d{1,2})?", raw_number):
            continue
        candidates.append(
            PriceCandidate(
                value=float(raw_number),
                raw=match.group(0),
                currency=_normalize_currency(leading_currency or trailing_currency),
                start=match.start(),
                end=match.end(),
            )
        )
    return candidates


def _normalize_currency(raw: str) -> str:
    value = raw.lower()
    if value in {"£", "gbp"}:
        return "GBP"
    if value in {"$", "usd"}:
        return "USD"
    if value in {"€", "eur"}:
        return "EUR"
    return "RUB"
