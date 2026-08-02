"""Tests for the Quality Controller (CQI aggregator)."""

from __future__ import annotations

import unittest

from app.content_pipeline.quality_controller import build_quality_report
from app.content_pipeline.schemas import (
    DescriptionGenerationResult,
    FactCheckResult,
    MarketplaceValidationResult,
    SEOAuditSummary,
)


def _description(text: str = "Короткое описание. С двумя предложениями.") -> DescriptionGenerationResult:
    return DescriptionGenerationResult(short_description="кратко", full_description=text)


class QualityControllerTests(unittest.TestCase):
    def test_high_scores_yield_high_cqi(self):
        report = build_quality_report(
            seo=SEOAuditSummary(score=95, tier="strong", ready=True),
            marketplace=MarketplaceValidationResult(ready=True, score=95),
            fact_check=FactCheckResult(confirmed_count=5, contradicted_count=0, unverifiable_count=0, passed=True),
            description=_description(),
            image_count=5,
        )
        self.assertGreaterEqual(report.cqi, 85)
        self.assertTrue(report.marketplace_ready)

    def test_contradicted_facts_lower_cqi(self):
        good = build_quality_report(
            seo=SEOAuditSummary(score=90, tier="strong", ready=True),
            marketplace=MarketplaceValidationResult(ready=True, score=90),
            fact_check=FactCheckResult(confirmed_count=5, contradicted_count=0, unverifiable_count=0, passed=True),
            description=_description(),
            image_count=5,
        )
        bad = build_quality_report(
            seo=SEOAuditSummary(score=90, tier="strong", ready=True),
            marketplace=MarketplaceValidationResult(ready=True, score=90),
            fact_check=FactCheckResult(confirmed_count=1, contradicted_count=4, unverifiable_count=0, passed=False),
            description=_description(),
            image_count=5,
        )
        self.assertLess(bad.cqi, good.cqi)

    def test_no_images_lowers_visual_score(self):
        report = build_quality_report(
            seo=SEOAuditSummary(score=90, tier="strong", ready=True),
            marketplace=MarketplaceValidationResult(ready=True, score=90),
            fact_check=FactCheckResult(passed=True),
            description=_description(),
            image_count=0,
        )
        self.assertEqual(report.visual_ready_score, 0)

    def test_empty_description_gets_zero_readability(self):
        report = build_quality_report(
            seo=SEOAuditSummary(score=50, tier="needs_work", ready=False),
            marketplace=MarketplaceValidationResult(ready=False, score=50),
            fact_check=FactCheckResult(passed=True),
            description=DescriptionGenerationResult(short_description="", full_description=""),
            image_count=1,
        )
        self.assertEqual(report.readability_score, 0)

    def test_breakdown_keys_present(self):
        report = build_quality_report(
            seo=SEOAuditSummary(score=80, tier="usable", ready=True),
            marketplace=MarketplaceValidationResult(ready=True, score=80),
            fact_check=FactCheckResult(passed=True),
            description=_description(),
            image_count=3,
        )
        self.assertEqual(set(report.breakdown), {"seo", "marketplace", "facts", "readability", "visual"})


if __name__ == "__main__":
    unittest.main()
