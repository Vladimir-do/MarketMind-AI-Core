"""Источники ключевых слов для семантического ядра."""

from __future__ import annotations

import csv
import io
from typing import Protocol

from app.products.schema import UnifiedProduct
from app.seo_intelligence import extract_competitor_terms


class KeywordSource(Protocol):
    """Абстрактный интерфейс источника ключевых слов."""

    def get_keywords(self, product: UnifiedProduct) -> list[str]:
        """Возвращает список ключевых слов для товара."""
        ...


class ManualCSVSource:
    """Импорт ключевых слов из CSV с колонками keyword, frequency, marketplace, category."""

    def __init__(self, data: str | bytes) -> None:
        if isinstance(data, bytes):
            text = data.decode("utf-8-sig")
        else:
            text = data
        self._rows = list(csv.DictReader(io.StringIO(text)))

    def get_keywords(self, product: UnifiedProduct) -> list[str]:  # noqa: ARG002
        keywords: list[str] = []
        seen: set[str] = set()
        for row in self._rows:
            keyword = (row.get("keyword") or "").strip().lower()
            if not keyword or keyword in seen:
                continue
            seen.add(keyword)
            keywords.append(keyword)
        rows_with_freq = [
            (row.get("keyword", "").strip().lower(), _parse_frequency(row.get("frequency")))
            for row in self._rows
            if (row.get("keyword") or "").strip()
        ]
        if rows_with_freq and any(freq for _, freq in rows_with_freq):
            freq_map: dict[str, int] = {}
            for kw, freq in rows_with_freq:
                if kw in freq_map:
                    freq_map[kw] = max(freq_map[kw], freq)
                else:
                    freq_map[kw] = freq
            keywords = sorted(freq_map, key=lambda k: -freq_map[k])
        return keywords


class CompetitorSource:
    """Извлечение ключевых слов из карточек конкурентов."""

    def __init__(self, competitors: list[dict]) -> None:
        self._competitors = competitors

    def get_keywords(self, product: UnifiedProduct) -> list[str]:  # noqa: ARG002
        return extract_competitor_terms(self._competitors)


def merge_keyword_sources(
    sources: list[KeywordSource],
    product: UnifiedProduct,
    *,
    limit: int = 50,
) -> list[str]:
    """Объединяет результаты всех источников, удаляет дубли, сохраняет приоритет."""
    result: list[str] = []
    seen: set[str] = set()
    for source in sources:
        for keyword in source.get_keywords(product):
            if keyword not in seen:
                seen.add(keyword)
                result.append(keyword)
    return result[:limit]


def _parse_frequency(value: str | None) -> int:
    if value is None:
        return 0
    normalized = str(value).strip().replace(" ", "").replace(",", ".")
    if not normalized:
        return 0
    try:
        return max(0, int(float(normalized)))
    except ValueError:
        return 0
