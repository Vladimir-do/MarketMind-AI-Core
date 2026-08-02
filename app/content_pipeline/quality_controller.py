"""Quality Controller — финальная стадия, агрегирует уже посчитанные оценки в единый CQI.

Не новая ML-модель: композиция SEO Auditor / Marketplace Validator /
Fact Checker и простой оценки читабельности/визуальной готовности текста.
"""

from __future__ import annotations

from app.content_pipeline.schemas import (
    DescriptionGenerationResult,
    FactCheckResult,
    MarketplaceValidationResult,
    QualityReport,
    SEOAuditSummary,
)

_WEIGHTS = {
    "seo": 0.30,
    "marketplace": 0.20,
    "facts": 0.25,
    "readability": 0.15,
    "visual": 0.10,
}


def _fact_check_pass_rate(fact_check: FactCheckResult) -> float:
    checked = fact_check.confirmed_count + fact_check.contradicted_count
    if checked == 0:
        return 1.0
    return fact_check.confirmed_count / checked


def _readability_score(description: DescriptionGenerationResult) -> int:
    text = description.full_description or ""
    if not text:
        return 0
    sentences = [s for s in text.replace("!", ".").replace("?", ".").split(".") if s.strip()]
    if not sentences:
        return 40
    avg_len = sum(len(s.split()) for s in sentences) / len(sentences)
    # короткие/средние предложения — лучше читаемость
    if avg_len <= 14:
        return 100
    if avg_len <= 22:
        return 80
    if avg_len <= 30:
        return 55
    return 30


def _visual_ready_score(passport_image_count: int) -> int:
    if passport_image_count >= 5:
        return 100
    if passport_image_count >= 3:
        return 75
    if passport_image_count >= 1:
        return 40
    return 0


def build_quality_report(
    *,
    seo: SEOAuditSummary,
    marketplace: MarketplaceValidationResult,
    fact_check: FactCheckResult,
    description: DescriptionGenerationResult,
    image_count: int,
) -> QualityReport:
    fact_pass_rate = _fact_check_pass_rate(fact_check)
    readability = _readability_score(description)
    visual = _visual_ready_score(image_count)

    breakdown = {
        "seo": seo.score,
        "marketplace": marketplace.score,
        "facts": round(fact_pass_rate * 100),
        "readability": readability,
        "visual": visual,
    }
    cqi = round(
        breakdown["seo"] * _WEIGHTS["seo"]
        + breakdown["marketplace"] * _WEIGHTS["marketplace"]
        + breakdown["facts"] * _WEIGHTS["facts"]
        + breakdown["readability"] * _WEIGHTS["readability"]
        + breakdown["visual"] * _WEIGHTS["visual"]
    )

    return QualityReport(
        seo_score=seo.score,
        marketplace_ready=marketplace.ready,
        fact_check_pass_rate=round(fact_pass_rate, 4),
        readability_score=readability,
        visual_ready_score=visual,
        cqi=cqi,
        breakdown=breakdown,
    )
