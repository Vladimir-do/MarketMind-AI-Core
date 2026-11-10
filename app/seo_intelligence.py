"""Deterministic SEO audit for marketplace product cards."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.seo_rules import SEOMarketplaceRule, get_marketplace_rules

if TYPE_CHECKING:
    from app.card_filler import OzonCardDraft
    from app.products.schema import UnifiedProduct


TITLE_MIN_CHARS = 25
TITLE_MAX_CHARS = 140
DESCRIPTION_MIN_CHARS = 350
MIN_KEYWORDS = 6
MIN_ATTRIBUTES = 4
MIN_IMAGES = 3

FORBIDDEN_MARKETING_WORDS = frozenset(
    {
        "лучший",
        "топ",
        "скидка",
        "акция",
        "купить",
        "дешево",
        "недорого",
        "гарантируем",
    }
)

GENERIC_PRODUCT_TYPES = frozenset(
    {
        "товар",
        "продукт",
        "изделие",
        "набор",
        "аксессуар",
    }
)


@dataclass(frozen=True)
class SEOFinding:
    rule: str
    field: str
    severity: str
    message: str


@dataclass(frozen=True)
class SEORecommendation:
    field: str
    action: str
    priority: int
    reason: str


@dataclass
class SEOAuditResult:
    score: int
    tier: str
    findings: list[SEOFinding] = field(default_factory=list)
    recommendations: list[SEORecommendation] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.score >= 75 and not any(item.severity == "critical" for item in self.findings)


def audit_ozon_card_seo(
    draft: OzonCardDraft,
    *,
    competitor_terms: list[str] | None = None,
    rules: SEOMarketplaceRule | None = None,
) -> SEOAuditResult:
    """Audit an Ozon card draft without mutating it."""
    if rules is None:
        rules = get_marketplace_rules("universal")
    competitor_terms = _normalize_terms(competitor_terms or [])
    findings: list[SEOFinding] = []
    findings.extend(_check_title(draft, rules=rules))
    findings.extend(_check_description(draft, rules=rules))
    findings.extend(_check_keywords(draft, competitor_terms, rules=rules))
    findings.extend(_check_content_depth(draft, rules=rules))

    score = _score(findings)
    recommendations = _recommend(findings)
    return SEOAuditResult(
        score=score,
        tier=_tier(score),
        findings=findings,
        recommendations=recommendations,
    )


def audit_unified_product_seo(
    product: UnifiedProduct,
    *,
    competitor_terms: list[str] | None = None,
    rules: SEOMarketplaceRule | None = None,
) -> SEOAuditResult:
    """Audit a marketplace-neutral product snapshot without mutating it."""
    if rules is None:
        rules = get_marketplace_rules("universal")
    competitor_terms = _normalize_terms(competitor_terms or [])
    findings: list[SEOFinding] = []
    findings.extend(_check_snapshot_title(product.name or "", rules=rules))
    findings.extend(_check_snapshot_description(product.description or "", rules=rules))
    findings.extend(_check_snapshot_keywords(product.tags, product.name or "", competitor_terms, rules=rules))
    findings.extend(
        _check_snapshot_depth(
            category=product.category,
            attributes=dict(product.attributes) if product.attributes else {},
            image_count=len(product.image_urls) if product.image_urls else 0,
            rules=rules,
        )
    )
    from app.semantic_core import build_semantic_core, semantic_coverage_findings

    semantic = build_semantic_core(
        name=product.name,
        description=product.description,
        attributes=dict(product.attributes) if product.attributes else None,
        category=product.category,
        tags=product.tags,
        brand=product.brand,
        rules=rules,
    )
    findings.extend(semantic_coverage_findings(semantic))
    score = _score(findings)
    return SEOAuditResult(
        score=score,
        tier=_tier(score),
        findings=findings,
        recommendations=_recommend(findings),
    )


def extract_competitor_terms(competitors: list[dict], *, limit: int = 20) -> list[str]:
    """Extract repeated meaningful terms from competitor names."""
    counts: dict[str, int] = {}
    for item in competitors:
        name = str(item.get("name") or "")
        for token in _tokens(name):
            if token in FORBIDDEN_MARKETING_WORDS or token in GENERIC_PRODUCT_TYPES:
                continue
            counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [term for term, count in ranked if count > 1][:limit]


def _check_title(draft: OzonCardDraft, *, rules: SEOMarketplaceRule | None = None) -> list[SEOFinding]:
    return _check_snapshot_title(draft.name or "", rules=rules)


def _check_snapshot_title(title: str, *, rules: SEOMarketplaceRule | None = None) -> list[SEOFinding]:
    if rules is None:
        rules = get_marketplace_rules("universal")
    findings: list[SEOFinding] = []
    if len(title) < rules.title_min:
        findings.append(SEOFinding("seo_title_short", "name", "warning", "Название слишком короткое для SEO-карточки."))
    if len(title) > rules.title_max:
        findings.append(
            SEOFinding("seo_title_long", "name", "critical", f"Название превышает лимит {rules.title_max} символов.")
        )
    title_tokens = _tokens(title)
    if not title_tokens or title_tokens[0] in GENERIC_PRODUCT_TYPES:
        findings.append(
            SEOFinding(
                "seo_title_product_type", "name", "warning", "Название должно начинаться с понятного типа товара."
            )
        )
    bad_words = sorted(set(title_tokens) & rules.forbidden_words)
    if bad_words:
        findings.append(
            SEOFinding(
                "seo_title_forbidden_words",
                "name",
                "warning",
                f"В названии есть рискованные слова: {', '.join(bad_words)}.",
            )
        )
    return findings


def _check_description(draft: OzonCardDraft, *, rules: SEOMarketplaceRule | None = None) -> list[SEOFinding]:
    return _check_snapshot_description(draft.description or "", rules=rules)


def _check_snapshot_description(description: str, *, rules: SEOMarketplaceRule | None = None) -> list[SEOFinding]:
    if rules is None:
        rules = get_marketplace_rules("universal")
    findings: list[SEOFinding] = []
    if len(description) < rules.description_min:
        findings.append(
            SEOFinding(
                "seo_description_short",
                "description",
                "warning",
                "Описание недостаточно раскрывает товар и сценарии использования.",
            )
        )
    if "Преимущества:" not in description:
        findings.append(
            SEOFinding(
                "seo_description_benefits", "description", "info", "В описании нет отдельного блока преимуществ."
            )
        )
    bad_words = sorted(set(_tokens(description)) & rules.forbidden_words)
    if bad_words:
        findings.append(
            SEOFinding(
                "seo_description_forbidden_words",
                "description",
                "warning",
                f"В описании есть рискованные слова: {', '.join(bad_words)}.",
            )
        )
    return findings


def _check_keywords(
    draft: OzonCardDraft, competitor_terms: list[str], *, rules: SEOMarketplaceRule | None = None
) -> list[SEOFinding]:
    return _check_snapshot_keywords(draft.keywords, draft.name or "", competitor_terms, rules=rules)


def _check_snapshot_keywords(
    keywords_raw: list[str] | None, title: str, competitor_terms: list[str], *, rules: SEOMarketplaceRule | None = None
) -> list[SEOFinding]:
    if rules is None:
        rules = get_marketplace_rules("universal")
    keywords = _normalize_terms(keywords_raw or [])
    findings: list[SEOFinding] = []
    if len(keywords) < rules.min_keywords:
        findings.append(
            SEOFinding(
                "seo_keywords_few", "keywords", "warning", "Слишком мало SEO-ключей для проверки полноты карточки."
            )
        )
    missing_competitor_terms = [
        term for term in competitor_terms if term not in keywords and term not in _tokens(title)
    ]
    if missing_competitor_terms:
        findings.append(
            SEOFinding(
                "seo_keywords_competitor_gap",
                "keywords",
                "info",
                "Не покрыты частые слова конкурентов: " + ", ".join(missing_competitor_terms[:8]) + ".",
            )
        )
    return findings


def _check_content_depth(draft: OzonCardDraft, *, rules: SEOMarketplaceRule | None = None) -> list[SEOFinding]:
    return _check_snapshot_depth(
        category=draft.category_hint,
        attributes=draft.attributes,
        image_count=len(draft.images),
        selling_point_count=len(draft.selling_points),
        rules=rules,
    )


def _check_snapshot_depth(
    *,
    category: str | None,
    attributes: dict[str, str],
    image_count: int,
    selling_point_count: int | None = None,
    rules: SEOMarketplaceRule | None = None,
) -> list[SEOFinding]:
    if rules is None:
        rules = get_marketplace_rules("universal")
    findings: list[SEOFinding] = []
    if not category:
        findings.append(
            SEOFinding("seo_category_missing", "category_hint", "warning", "Не указана категория карточки.")
        )
    if len(attributes) < rules.min_attributes:
        findings.append(
            SEOFinding(
                "seo_attributes_few",
                "attributes",
                "warning",
                "Недостаточно характеристик для SEO и фильтров маркетплейса.",
            )
        )
    if image_count < rules.min_images:
        findings.append(SEOFinding("seo_images_few", "images", "info", "Для карточки желательно 3+ изображения."))
    if selling_point_count is not None and selling_point_count < 3:
        findings.append(
            SEOFinding(
                "seo_selling_points_few", "selling_points", "info", "Добавьте 3-4 конкретных преимущества товара."
            )
        )
    return findings


def _score(findings: list[SEOFinding]) -> int:
    score = 100
    for finding in findings:
        if finding.severity == "critical":
            score -= 25
        elif finding.severity == "warning":
            score -= 10
        else:
            score -= 4
    return max(0, min(100, score))


def _tier(score: int) -> str:
    if score >= 85:
        return "strong"
    if score >= 70:
        return "usable"
    if score >= 50:
        return "needs_work"
    return "weak"


def _recommend(findings: list[SEOFinding]) -> list[SEORecommendation]:
    priorities = {"critical": 1, "warning": 2, "info": 3}
    actions = {
        "seo_title_short": "Расширить название: тип товара + ключевые свойства + бренд.",
        "seo_title_long": "Сократить название до 140 символов.",
        "seo_title_product_type": "Начать название с конкретного типа товара.",
        "seo_title_forbidden_words": "Убрать рекламные обещания из названия.",
        "seo_description_short": "Расширить описание: назначение, сценарии, преимущества, характеристики.",
        "seo_description_benefits": "Добавить блок преимуществ в описание.",
        "seo_description_forbidden_words": "Убрать рискованные обещания из описания.",
        "seo_keywords_few": "Добавить релевантные ключевые слова из названия, категории и характеристик.",
        "seo_keywords_competitor_gap": "Добавить недостающие частые слова конкурентов, если они правдиво описывают товар.",
        "seo_category_missing": "Уточнить категорию Ozon.",
        "seo_attributes_few": "Заполнить характеристики, которые участвуют в фильтрах и поиске.",
        "seo_images_few": "Добавить главное фото и 2-4 дополнительных ракурса.",
        "seo_selling_points_few": "Сформулировать 3-4 преимущества без неподтвержденных обещаний.",
    }
    return [
        SEORecommendation(
            field=finding.field,
            action=actions.get(finding.rule, "Проверить SEO-поле карточки."),
            priority=priorities.get(finding.severity, 3),
            reason=finding.message,
        )
        for finding in sorted(findings, key=lambda item: priorities.get(item.severity, 3))
    ]


def _tokens(text: str) -> list[str]:
    return [token for token in re.findall(r"[A-Za-zА-Яа-яЁё0-9+]{3,}", (text or "").lower()) if not token.isdigit()]


def _normalize_terms(terms: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for term in terms:
        clean = " ".join(_tokens(str(term)))
        if clean and clean not in seen:
            seen.add(clean)
            normalized.append(clean)
    return normalized
