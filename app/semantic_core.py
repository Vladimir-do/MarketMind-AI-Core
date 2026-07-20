"""Semantic Core — детерминированный extractor семантического ядра товара."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from app.seo_intelligence import SEOFinding, _tokens
from app.seo_rules import SEOMarketplaceRule

_NOISY_PATTERN = re.compile(r"[A-Z]{2,}\d{3,}")


@dataclass(frozen=True)
class SemanticCore:
    """Семантическое ядро товара — классифицированные ключевые слова."""

    primary_terms: list[str]
    secondary_terms: list[str]
    long_tail_terms: list[str]
    brand_terms: list[str]
    attribute_terms: list[str]
    category_terms: list[str]
    forbidden_terms: list[str]
    noisy_terms: list[str]
    total_terms: int
    coverage_score: float
    junk_ratio: float


def build_semantic_core(
    name: str | None,
    description: str | None,
    attributes: dict[str, str] | None,
    category: str | None,
    tags: list[str] | None,
    brand: str | None,
    rules: SEOMarketplaceRule | None = None,
) -> SemanticCore:
    """Строит семантическое ядро для товара.

    Извлекает токены из name, description, attributes, category, tags.
    Классифицирует каждый токен по роли: primary, secondary, long_tail,
    brand, attribute, category, forbidden, noisy.
    """
    # Собираем токены из всех источников
    name_tokens = _tokens(name or "")
    desc_tokens = _tokens(description or "")
    tag_tokens = _tokens(" ".join(tags or []))
    attr_key_tokens: list[str] = []
    attr_val_tokens: list[str] = []
    if attributes:
        for key, val in attributes.items():
            attr_key_tokens.extend(_tokens(key))
            attr_val_tokens.extend(_tokens(val))
    cat_tokens = _tokens(category or "")

    # Общая частота по всем источникам
    all_tokens = name_tokens + desc_tokens + tag_tokens + attr_key_tokens + attr_val_tokens + cat_tokens
    freq = Counter(all_tokens)

    # Множества токенов по источникам для определения primary
    name_set = set(name_tokens)
    attr_set = set(attr_key_tokens) | set(attr_val_tokens)
    tag_set = set(tag_tokens)

    forbidden_words = rules.forbidden_words if rules else frozenset()
    brand_lower = (brand or "").lower()

    # Классификация
    primary: list[str] = []
    secondary: list[str] = []
    long_tail: list[str] = []
    brand_list: list[str] = []
    attribute_list: list[str] = []
    category_list: list[str] = []
    forbidden_list: list[str] = []
    noisy_list: list[str] = []

    seen: set[str] = set()
    for token, count in freq.most_common():
        if token in seen:
            continue
        seen.add(token)

        # Запрещённые слова
        if token in forbidden_words:
            forbidden_list.append(token)
            continue

        # Шумовые — артикулы вида AB123
        if _NOISY_PATTERN.fullmatch(token.upper()):
            noisy_list.append(token)
            continue

        # Брендовые
        if brand_lower and token in brand_lower.split():
            brand_list.append(token)
            continue

        # Атрибутные — из ключей/значений attributes
        if token in attr_set:
            attribute_list.append(token)
            continue

        # Категорийные — из category
        if token in cat_tokens and token not in name_set:
            category_list.append(token)
            continue

        # Primary — есть в title И (attributes ИЛИ tags)
        if token in name_set and (token in attr_set or token in tag_set):
            primary.append(token)
            continue

        # Secondary — частота > 1
        if count > 1:
            secondary.append(token)
            continue

        # Long tail — частота == 1
        long_tail.append(token)

    # Ограничиваем primary до 3
    primary = primary[:3]

    total = (
        len(primary)
        + len(secondary)
        + len(long_tail)
        + len(brand_list)
        + len(attribute_list)
        + len(category_list)
        + len(forbidden_list)
        + len(noisy_list)
    )

    useful = len(primary) + len(secondary)
    total_useful = useful + len(long_tail)
    coverage = useful / max(total_useful, 1)
    junk = (len(forbidden_list) + len(noisy_list)) / max(total, 1)

    return SemanticCore(
        primary_terms=primary,
        secondary_terms=secondary,
        long_tail_terms=long_tail,
        brand_terms=brand_list,
        attribute_terms=attribute_list,
        category_terms=category_list,
        forbidden_terms=forbidden_list,
        noisy_terms=noisy_list,
        total_terms=total,
        coverage_score=coverage,
        junk_ratio=junk,
    )


def semantic_coverage_findings(core: SemanticCore) -> list[SEOFinding]:
    """Генерирует SEO- находки на основе семантического ядра."""
    findings: list[SEOFinding] = []

    if not core.primary_terms:
        findings.append(SEOFinding(
            rule="seo_semantic_no_primary",
            field="keywords",
            severity="warning",
            message="Нет основных ключевых слов — определите 1-3 ключевых термина товара.",
        ))

    if len(core.secondary_terms) < 3:
        findings.append(SEOFinding(
            rule="seo_semantic_few_secondary",
            field="keywords",
            severity="info",
            message="Мало дополнительных ключевых слов (< 3). Добавьте смежные запросы.",
        ))

    if core.junk_ratio > 0.3:
        findings.append(SEOFinding(
            rule="seo_semantic_high_junk",
            field="keywords",
            severity="warning",
            message=f"Высокая доля мусорных слов ({core.junk_ratio:.0%}). Удалите запрещённые и шумовые токены.",
        ))

    if core.coverage_score < 0.3:
        findings.append(SEOFinding(
            rule="seo_semantic_low_coverage",
            field="keywords",
            severity="warning",
            message=f"Низкое покрытие ключевых слов ({core.coverage_score:.0%}). Добавьте релевантные термины.",
        ))

    return findings
