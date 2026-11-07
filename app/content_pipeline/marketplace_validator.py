"""Marketplace Validator — финальный блокирующий gate перед AI Proposal Queue.

Использует ту же audit_unified_product_seo(), что и SEO Auditor
(seo_auditor.py), но интерпретирует .ready как блокирующий критерий:
если карточка не готова — критичные findings попадают в blocking_issues
и предложение не должно считаться готовым к автопостановке в очередь
без явного внимания оператора.
"""

from __future__ import annotations

from app.content_pipeline.passport import passport_to_unified
from app.content_pipeline.schemas import MarketplaceValidationResult, ProductPassport
from app.seo_intelligence import audit_unified_product_seo
from app.seo_rules import get_marketplace_rules


def validate_for_marketplace(
    passport: ProductPassport,
    *,
    title: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
) -> MarketplaceValidationResult:
    product = passport_to_unified(passport, title=title, description=description, tags=tags)
    rules = get_marketplace_rules(passport.marketplace)
    result = audit_unified_product_seo(product, rules=rules)

    blocking = [f"{item.field}: {item.message}" for item in result.findings if item.severity == "critical"]
    warnings = [f"{item.field}: {item.message}" for item in result.findings if item.severity != "critical"]

    return MarketplaceValidationResult(
        ready=result.ready,
        score=result.score,
        blocking_issues=blocking,
        warnings=warnings,
    )
