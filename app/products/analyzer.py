"""Rule-based product intelligence analyzer."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence

from app.products.findings import AnalysisResult, BatchAnalysisResult, Finding, Recommendation
from app.products.schema import UnifiedProduct

# ── Thresholds ──────────────────────────────────────────────────────────

MIN_DESCRIPTION_LENGTH = 50
GENERIC_BRANDS = frozenset({"unknown", "n/a", "none", "generic", "misc", "brands"})
GENERIC_CATEGORIES = frozenset({"misc", "other", "uncategorized", "unspecified", "general"})
SCORE_EXCELLENT = 90
SCORE_GOOD = 75
SCORE_FAIR = 50
SCORE_POOR = 25
KNOWN_SOURCE_TYPES = frozenset({
    "ozon",
    "wildberries",
    "wb",
    "yandex",
    "yandex_market",
    "csv",
    "manual",
    "project_file_import",
    "file_import",
    "",
})


# ── Tier mapping ────────────────────────────────────────────────────────

def _get_tier(score: int) -> str:
    if score >= SCORE_EXCELLENT:
        return "excellent"
    if score >= SCORE_GOOD:
        return "good"
    if score >= SCORE_FAIR:
        return "fair"
    if score >= SCORE_POOR:
        return "poor"
    return "critical"


# ── Rule implementations ────────────────────────────────────────────────

def _check_completeness(product: UnifiedProduct) -> list[Finding]:
    findings: list[Finding] = []

    if not product.name or not product.name.strip():
        findings.append(Finding(
            rule="completeness_name",
            field="name",
            message="Product name is missing or empty",
            severity="critical",
            category="completeness",
        ))

    if product.price is None:
        findings.append(Finding(
            rule="completeness_price",
            field="price",
            message="Product price is missing",
            severity="critical",
            category="completeness",
        ))

    if not product.brand:
        findings.append(Finding(
            rule="completeness_brand",
            field="brand",
            message="Brand is not specified",
            severity="warning",
            category="completeness",
        ))

    if not product.category:
        findings.append(Finding(
            rule="completeness_category",
            field="category",
            message="Category is not specified",
            severity="warning",
            category="completeness",
        ))

    if not product.description:
        findings.append(Finding(
            rule="completeness_description",
            field="description",
            message="Product description is missing",
            severity="warning",
            category="completeness",
        ))

    if not product.image_urls:
        findings.append(Finding(
            rule="completeness_images",
            field="image_urls",
            message="No product images provided",
            severity="warning",
            category="completeness",
        ))

    if not product.sku:
        findings.append(Finding(
            rule="completeness_sku",
            field="sku",
            message="SKU is not set",
            severity="info",
            category="completeness",
        ))

    is_market_analysis = _is_market_analysis_candidate(product)

    if product.weight_g is None and not is_market_analysis:
        findings.append(Finding(
            rule="completeness_weight",
            field="weight_g",
            message="Weight is not specified",
            severity="info",
            category="completeness",
        ))

    if product.width_mm is None and product.height_mm is None and product.depth_mm is None and not is_market_analysis:
        findings.append(Finding(
            rule="completeness_dimensions",
            field="dimensions",
            message="No dimensions specified (width, height, depth)",
            severity="info",
            category="completeness",
        ))

    if not product.source_url:
        findings.append(Finding(
            rule="completeness_source_url",
            field="source_url",
            message="Source URL is not set",
            severity="info",
            category="completeness",
        ))

    return findings


def _check_consistency(product: UnifiedProduct) -> list[Finding]:
    findings: list[Finding] = []

    if product.price is not None and product.price <= 0:
        findings.append(Finding(
            rule="consistency_price_positive",
            field="price",
            message="Price must be a positive value",
            severity="critical",
            category="consistency",
        ))

    if product.old_price is not None and product.price is not None:
        if product.old_price <= product.price:
            findings.append(Finding(
                rule="consistency_old_price_gt_current",
                field="old_price",
                message="Old price should be greater than current price",
                severity="warning",
                category="consistency",
            ))

    if product.discount_pct is not None and product.old_price is not None and product.price is not None:
        if product.old_price > product.price:
            expected = round((1 - product.price / product.old_price) * 100)
            if abs(product.discount_pct - expected) > 1:
                findings.append(Finding(
                    rule="consistency_discount_pct",
                    field="discount_pct",
                    message=f"Discount {product.discount_pct}% doesn't match calculated {expected}%",
                    severity="info",
                    category="consistency",
                ))

    if len(product.name) > 200:
        findings.append(Finding(
            rule="consistency_name_length",
            field="name",
            message="Product name exceeds 200 characters",
            severity="info",
            category="consistency",
        ))

    if product.description and re.search(r"<[^>]+>", product.description):
        findings.append(Finding(
            rule="consistency_description_html",
            field="description",
            message="Description contains HTML tags — should be plain text",
            severity="warning",
            category="consistency",
        ))

    if product.source_type not in KNOWN_SOURCE_TYPES:
        findings.append(Finding(
            rule="consistency_source_type",
            field="source_type",
            message=f"Unknown source type: {product.source_type}",
            severity="info",
            category="consistency",
        ))

    return findings


def _is_market_analysis_candidate(product: UnifiedProduct) -> bool:
    values = [str(value).lower() for value in (product.attributes or {}).values()]
    return any("source=market_analysis" in value for value in values)


def _check_quality(product: UnifiedProduct) -> list[Finding]:
    findings: list[Finding] = []

    if product.description and len(product.description) < MIN_DESCRIPTION_LENGTH:
        findings.append(Finding(
            rule="quality_description_short",
            field="description",
            message=f"Description is only {len(product.description)} chars — aim for {MIN_DESCRIPTION_LENGTH}+",
            severity="info",
            category="quality",
        ))

    if product.brand and product.brand.strip().lower() in GENERIC_BRANDS:
        findings.append(Finding(
            rule="quality_generic_brand",
            field="brand",
            message=f"Brand '{product.brand}' appears to be a placeholder",
            severity="info",
            category="quality",
        ))

    if product.category and product.category.strip().lower() in GENERIC_CATEGORIES:
        findings.append(Finding(
            rule="quality_generic_category",
            field="category",
            message=f"Category '{product.category}' is too generic to be useful",
            severity="info",
            category="quality",
        ))

    if not product.attributes:
        findings.append(Finding(
            rule="quality_no_attributes",
            field="attributes",
            message="No product attributes defined",
            severity="info",
            category="quality",
        ))

    return findings


# ── Recommendations ─────────────────────────────────────────────────────

_SEVERITY_PRIORITY = {"critical": 1, "warning": 2, "info": 3}

_ACTION_MAP: dict[str, str] = {
    "completeness_name": "Add a descriptive product name",
    "completeness_price": "Set the product price",
    "completeness_brand": "Specify the brand name",
    "completeness_category": "Assign a product category",
    "completeness_description": "Write a detailed product description",
    "completeness_images": "Upload at least one product image",
    "completeness_sku": "Assign an SKU identifier",
    "completeness_weight": "Specify product weight in grams",
    "completeness_dimensions": "Add product dimensions (W x H x D mm)",
    "completeness_source_url": "Provide the source listing URL",
    "consistency_price_positive": "Correct the price to a positive value",
    "consistency_old_price_gt_current": "Set old_price higher than current price",
    "consistency_discount_pct": "Recalculate the discount percentage",
    "consistency_name_length": "Shorten the product name",
    "consistency_description_html": "Remove HTML tags from description",
    "consistency_source_type": "Use a known source type",
    "quality_description_short": "Expand the description with more details",
    "quality_generic_brand": "Replace placeholder brand with the real brand",
    "quality_generic_category": "Pick a specific category",
    "quality_no_attributes": "Add key-value product attributes",
}


def _build_recommendations(findings: list[Finding]) -> list[Recommendation]:
    recs: list[Recommendation] = []
    for f in findings:
        action = _ACTION_MAP.get(f.rule, f"Review: {f.rule}")
        recs.append(Recommendation(
            finding=f,
            action=action,
            priority=_SEVERITY_PRIORITY.get(f.severity, 3),
            description=f.message,
        ))
    return sorted(recs, key=lambda r: r.priority)


# ── Scoring ─────────────────────────────────────────────────────────────

_WEIGHTS: dict[str, int] = {
    "critical": 25,
    "warning": 10,
    "info": 3,
}

_FINDINGS_PER_FIELD: dict[str, int] = {
    "name": 1,
    "price": 1,
    "brand": 1,
    "category": 1,
    "description": 1,
    "image_urls": 1,
    "sku": 1,
    "weight_g": 1,
    "dimensions": 1,
    "source_url": 1,
}


def calculate_quality_score(product: UnifiedProduct) -> int:
    """Return 0-100 quality score. 100 = no findings at all."""
    all_findings = _check_completeness(product) + _check_consistency(product) + _check_quality(product)
    if not all_findings:
        return 100

    # Calculate penalty: start from 100, subtract weighted deductions
    penalty = 0
    for f in all_findings:
        penalty += _WEIGHTS.get(f.severity, 3)

    score = max(0, 100 - penalty)
    return min(100, score)


# ── Main analyzer ───────────────────────────────────────────────────────

class ProductAnalyzer:
    """Rule-based product quality analyzer."""

    def analyze(self, product: UnifiedProduct) -> AnalysisResult:
        completeness = _check_completeness(product)
        consistency = _check_consistency(product)
        quality = _check_quality(product)

        all_findings = completeness + consistency + quality
        score = calculate_quality_score(product)
        tier = _get_tier(score)
        recommendations = _build_recommendations(all_findings)

        return AnalysisResult(
            product=product,
            score=score,
            findings=all_findings,
            recommendations=recommendations,
            tier=tier,
        )

    def analyze_batch(self, products: Sequence[UnifiedProduct]) -> BatchAnalysisResult:
        results = [self.analyze(p) for p in products]
        total = len(results)

        if total == 0:
            return BatchAnalysisResult(
                total=0,
                average_score=0.0,
                score_distribution={},
                findings_summary={},
                top_recommendations=[],
                products_below_threshold=[],
            )

        avg_score = sum(r.score for r in results) / total

        tier_counter = Counter(r.tier for r in results)
        score_distribution = dict(tier_counter)

        finding_counter: Counter[str] = Counter()
        for r in results:
            for f in r.findings:
                finding_counter[f.rule] += 1
        findings_summary = dict(finding_counter.most_common())

        # Collect all recommendations, deduplicate by rule, take top 10
        all_recs: dict[str, Recommendation] = {}
        for r in results:
            for rec in r.recommendations:
                rule = rec.finding.rule
                if rule not in all_recs:
                    all_recs[rule] = rec
        top_recs = sorted(all_recs.values(), key=lambda x: x.priority)[:10]

        below = [
            r.product.name for r in results if r.score < SCORE_FAIR
        ]

        return BatchAnalysisResult(
            total=total,
            average_score=round(avg_score, 1),
            score_distribution=score_distribution,
            findings_summary=findings_summary,
            top_recommendations=top_recs,
            products_below_threshold=below,
        )
