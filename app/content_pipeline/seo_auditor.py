"""SEO Auditor — информационная стадия пайплайна (не блокирует).

Тонкая обёртка над app.seo_intelligence.audit_unified_product_seo() —
та же детерминированная логика, что и в Marketplace Validator (см.
marketplace_validator.py), чтобы пороги не расходились между двумя точками.
"""

from __future__ import annotations

from app.content_pipeline.passport import passport_to_unified
from app.content_pipeline.schemas import ProductPassport, SEOAuditSummary
from app.seo_intelligence import audit_unified_product_seo
from app.seo_rules import get_marketplace_rules


def audit_draft(
    passport: ProductPassport,
    *,
    title: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
) -> SEOAuditSummary:
    product = passport_to_unified(passport, title=title, description=description, tags=tags)
    rules = get_marketplace_rules(passport.marketplace)
    result = audit_unified_product_seo(product, rules=rules)
    return SEOAuditSummary(
        score=result.score,
        tier=result.tier,
        ready=result.ready,
        findings=[f"[{item.severity}] {item.field}: {item.message}" for item in result.findings],
        recommendations=[item.action for item in result.recommendations],
    )
