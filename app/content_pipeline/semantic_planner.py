"""Semantic Planner — распределяет уже классифицированные ключи по зонам карточки.

Не генерирует новые ключевые слова: чистка и классификация выполняются
в app.semantic_core.build_semantic_core(), здесь только распределение
по зонам title/benefits/description с учётом лимита длины названия.
"""

from __future__ import annotations

from app.content_pipeline.schemas import ProductPassport, SemanticPlan
from app.semantic_core import SemanticCore, build_semantic_core
from app.seo_intelligence import extract_competitor_terms
from app.seo_rules import SEOMarketplaceRule, get_marketplace_rules

_AVG_TERM_LEN_WITH_SEPARATOR = 8  # эвристика для оценки, сколько терминов влезет в title_max


def build_semantic_plan(
    core: SemanticCore,
    *,
    rules: SEOMarketplaceRule | None = None,
) -> SemanticPlan:
    active_rules = rules or get_marketplace_rules("universal")

    title_budget = max(1, active_rules.title_max // _AVG_TERM_LEN_WITH_SEPARATOR)
    title_terms = list(dict.fromkeys(core.primary_terms + core.brand_terms))[:title_budget]

    used = set(title_terms)
    benefits_terms = [
        term for term in (core.secondary_terms + core.attribute_terms) if term not in used
    ]
    used |= set(benefits_terms)

    description_terms = [
        term
        for term in (core.long_tail_terms + core.category_terms)
        if term not in used
    ]

    excluded_terms = list(dict.fromkeys(core.forbidden_terms + core.noisy_terms))

    return SemanticPlan(
        title_terms=title_terms,
        benefits_terms=benefits_terms,
        description_terms=description_terms,
        excluded_terms=excluded_terms,
    )


def semantic_plan_for_passport(
    passport: ProductPassport,
    *,
    marketplace: str | None = None,
    competitor_names: list[str] | None = None,
) -> tuple[SemanticCore, SemanticPlan]:
    """Строит SemanticCore и SemanticPlan напрямую из ProductPassport.

    Если переданы competitor_names (названия карточек конкурентов) —
    добавляет competitor_gap_terms: частые термины конкурентов, которых
    ещё нет в собственном плане (title/benefits/description). Использует
    существующий app.seo_intelligence.extract_competitor_terms(), ничего
    не дублирует. Опционально — если конкурентов ещё нет, план работает
    как раньше.
    """
    rules = get_marketplace_rules(marketplace or passport.marketplace)
    core = build_semantic_core(
        name=passport.title,
        description=passport.description,
        attributes=passport.attributes,
        category=passport.category,
        tags=passport.tags,
        brand=passport.brand,
        rules=rules,
    )
    plan = build_semantic_plan(core, rules=rules)

    if competitor_names:
        competitor_terms = extract_competitor_terms([{"name": name} for name in competitor_names])
        covered = set(plan.title_terms) | set(plan.benefits_terms) | set(plan.description_terms)
        gap_terms = [term for term in competitor_terms if term not in covered]
        plan = plan.model_copy(update={"competitor_gap_terms": gap_terms})

    return core, plan
