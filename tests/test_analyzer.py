"""Tests for the Product Intelligence Analyzer."""

from __future__ import annotations

import unittest

from app.products.analyzer import ProductAnalyzer, calculate_quality_score, _get_tier
from app.products.schema import UnifiedProduct


def _make_product(**overrides) -> UnifiedProduct:
    defaults = {
        "name": "Test Product",
        "source_id": "12345",
        "source_type": "ozon",
        "description": "A high-quality test product with sufficient description text",
        "brand": "TestBrand",
        "category": "Electronics",
        "sku": "SKU-001",
        "price": 1000,
        "old_price": 1500,
        "discount_pct": 33,
        "weight_g": 500,
        "width_mm": 100,
        "height_mm": 50,
        "depth_mm": 30,
        "image_urls": ["https://example.com/img.jpg"],
        "source_url": "https://example.com/product",
    }
    defaults.update(overrides)
    return UnifiedProduct(**defaults)


class TestQualityScore(unittest.TestCase):
    def test_excellent_product(self):
        """A fully-filled product should score 80+."""
        product = _make_product()
        score = calculate_quality_score(product)
        self.assertGreaterEqual(score, 80)

    def test_score_ranges(self):
        """Score should always be between 0 and 100."""
        # Perfect product
        score = calculate_quality_score(_make_product())
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

        # Empty product
        empty = UnifiedProduct(name="", source_id="", source_type="")
        score = calculate_quality_score(empty)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)


class TestCompletenessFindings(unittest.TestCase):
    def test_missing_name_gives_critical_finding(self):
        product = _make_product(name="")
        analyzer = ProductAnalyzer()
        result = analyzer.analyze(product)
        name_findings = [f for f in result.findings if f.rule == "completeness_name"]
        self.assertEqual(len(name_findings), 1)
        self.assertEqual(name_findings[0].severity, "critical")

    def test_missing_price_gives_critical_finding(self):
        product = _make_product(price=None)
        analyzer = ProductAnalyzer()
        result = analyzer.analyze(product)
        price_findings = [f for f in result.findings if f.rule == "completeness_price"]
        self.assertEqual(len(price_findings), 1)
        self.assertEqual(price_findings[0].severity, "critical")

    def test_missing_brand_gives_warning_finding(self):
        product = _make_product(brand=None)
        analyzer = ProductAnalyzer()
        result = analyzer.analyze(product)
        brand_findings = [f for f in result.findings if f.rule == "completeness_brand"]
        self.assertEqual(len(brand_findings), 1)
        self.assertEqual(brand_findings[0].severity, "warning")

    def test_missing_category_gives_warning_finding(self):
        product = _make_product(category=None)
        analyzer = ProductAnalyzer()
        result = analyzer.analyze(product)
        cat_findings = [f for f in result.findings if f.rule == "completeness_category"]
        self.assertEqual(len(cat_findings), 1)
        self.assertEqual(cat_findings[0].severity, "warning")


class TestConsistencyFindings(unittest.TestCase):
    def test_price_nonpositive_gives_critical(self):
        product = _make_product(price=0)
        analyzer = ProductAnalyzer()
        result = analyzer.analyze(product)
        price_findings = [f for f in result.findings if f.rule == "consistency_price_positive"]
        self.assertEqual(len(price_findings), 1)
        self.assertEqual(price_findings[0].severity, "critical")

    def test_old_price_not_greater_gives_warning(self):
        product = _make_product(price=1000, old_price=800)
        analyzer = ProductAnalyzer()
        result = analyzer.analyze(product)
        old_price_findings = [f for f in result.findings if f.rule == "consistency_old_price_gt_current"]
        self.assertEqual(len(old_price_findings), 1)
        self.assertEqual(old_price_findings[0].severity, "warning")

    def test_discount_mismatch_gives_info(self):
        # 1000 vs 1500 = 33.33% discount, but listed as 30%
        product = _make_product(price=1000, old_price=1500, discount_pct=30)
        analyzer = ProductAnalyzer()
        result = analyzer.analyze(product)
        discount_findings = [f for f in result.findings if f.rule == "consistency_discount_pct"]
        self.assertEqual(len(discount_findings), 1)
        self.assertEqual(discount_findings[0].severity, "info")


class TestQualityFindings(unittest.TestCase):
    def test_description_too_short_gives_info(self):
        product = _make_product(description="Short")
        analyzer = ProductAnalyzer()
        result = analyzer.analyze(product)
        desc_findings = [f for f in result.findings if f.rule == "quality_description_short"]
        self.assertEqual(len(desc_findings), 1)
        self.assertEqual(desc_findings[0].severity, "info")

    def test_generic_brand_gives_info(self):
        product = _make_product(brand="Unknown")
        analyzer = ProductAnalyzer()
        result = analyzer.analyze(product)
        brand_findings = [f for f in result.findings if f.rule == "quality_generic_brand"]
        self.assertEqual(len(brand_findings), 1)
        self.assertEqual(brand_findings[0].severity, "info")


class TestBatchAnalysis(unittest.TestCase):
    def test_batch_analysis_calculates_average(self):
        products = [
            _make_product(name="Product 1", price=1000),
            _make_product(name="Product 2", price=2000),
        ]
        analyzer = ProductAnalyzer()
        result = analyzer.analyze_batch(products)
        self.assertEqual(result.total, 2)
        self.assertGreater(result.average_score, 0)

    def test_batch_analysis_finds_low_scores(self):
        products = [
            _make_product(),  # good product
            UnifiedProduct(name="", source_id="", source_type=""),  # bad product
        ]
        analyzer = ProductAnalyzer()
        result = analyzer.analyze_batch(products)
        self.assertEqual(len(result.products_below_threshold), 1)


class TestTierClassification(unittest.TestCase):
    def test_tier_classification(self):
        self.assertEqual(_get_tier(95), "excellent")
        self.assertEqual(_get_tier(80), "good")
        self.assertEqual(_get_tier(60), "fair")
        self.assertEqual(_get_tier(30), "poor")
        self.assertEqual(_get_tier(10), "critical")

    def test_tier_in_result(self):
        product = _make_product()
        analyzer = ProductAnalyzer()
        result = analyzer.analyze(product)
        self.assertIn(result.tier, ["excellent", "good", "fair", "poor", "critical"])


if __name__ == "__main__":
    unittest.main()
