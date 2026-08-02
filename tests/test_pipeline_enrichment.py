"""Extended tests for pipeline enrichment and edge cases."""

import unittest
from unittest.mock import patch

from app.enrichers.ozon_enricher import OzonEnrichmentStrategy
from app.pipeline import ImportPipeline, PipelineResult
from app.products.schema import UnifiedProduct


class NormalizeTextTests(unittest.TestCase):
    """Tests for _normalize_text whitespace collapsing."""

    def test_collapses_multiple_spaces(self):
        product = UnifiedProduct(name="  Product   A  ", source_id="1", source_type="test")
        pipeline = ImportPipeline(strategy=None)
        result = pipeline._normalize_text(product)
        self.assertEqual(result.name, "Product A")

    def test_collapses_tabs_and_newlines(self):
        product = UnifiedProduct(name="Product\t\tA\n\nB", source_id="1", source_type="test")
        pipeline = ImportPipeline(strategy=None)
        result = pipeline._normalize_text(product)
        self.assertEqual(result.name, "Product A B")

    def test_normalizes_description(self):
        product = UnifiedProduct(
            name="X", source_id="1", source_type="test",
            description="  long   description   with   spaces  ",
        )
        pipeline = ImportPipeline(strategy=None)
        result = pipeline._normalize_text(product)
        self.assertEqual(result.description, "long description with spaces")

    def test_normalizes_brand(self):
        product = UnifiedProduct(
            name="X", source_id="1", source_type="test",
            brand="  Some   Brand  ",
        )
        pipeline = ImportPipeline(strategy=None)
        result = pipeline._normalize_text(product)
        self.assertEqual(result.brand, "Some Brand")

    def test_normalizes_category(self):
        product = UnifiedProduct(
            name="X", source_id="1", source_type="test",
            category="  Electronics  /  Phones  ",
        )
        pipeline = ImportPipeline(strategy=None)
        result = pipeline._normalize_text(product)
        self.assertEqual(result.category, "Electronics / Phones")

    def test_empty_name_becomes_empty_string(self):
        product = UnifiedProduct(name="", source_id="1", source_type="test")
        pipeline = ImportPipeline(strategy=None)
        result = pipeline._normalize_text(product)
        self.assertEqual(result.name, "")

    def test_none_description_stays_none(self):
        product = UnifiedProduct(name="X", source_id="1", source_type="test", description=None)
        pipeline = ImportPipeline(strategy=None)
        result = pipeline._normalize_text(product)
        self.assertIsNone(result.description)

    def test_none_brand_stays_none(self):
        product = UnifiedProduct(name="X", source_id="1", source_type="test", brand=None)
        pipeline = ImportPipeline(strategy=None)
        result = pipeline._normalize_text(product)
        self.assertIsNone(result.brand)


class FillMissingDataTests(unittest.TestCase):
    """Tests for _fill_missing_data discount_pct derivation."""

    def test_derives_discount_pct(self):
        product = UnifiedProduct(
            name="X", source_id="1", source_type="test",
            price=800, old_price=1000, discount_pct=None,
        )
        pipeline = ImportPipeline(strategy=None)
        result = pipeline._fill_missing_data(product)
        self.assertEqual(result.discount_pct, 20)

    def test_does_not_override_existing_discount(self):
        product = UnifiedProduct(
            name="X", source_id="1", source_type="test",
            price=800, old_price=1000, discount_pct=15,
        )
        pipeline = ImportPipeline(strategy=None)
        result = pipeline._fill_missing_data(product)
        self.assertEqual(result.discount_pct, 15)

    def test_no_discount_when_old_price_less_than_price(self):
        product = UnifiedProduct(
            name="X", source_id="1", source_type="test",
            price=1000, old_price=800, discount_pct=None,
        )
        pipeline = ImportPipeline(strategy=None)
        result = pipeline._fill_missing_data(product)
        self.assertIsNone(result.discount_pct)

    def test_no_discount_when_price_is_none(self):
        product = UnifiedProduct(
            name="X", source_id="1", source_type="test",
            price=None, old_price=1000, discount_pct=None,
        )
        pipeline = ImportPipeline(strategy=None)
        result = pipeline._fill_missing_data(product)
        self.assertIsNone(result.discount_pct)

    def test_no_discount_when_old_price_is_none(self):
        product = UnifiedProduct(
            name="X", source_id="1", source_type="test",
            price=1000, old_price=None, discount_pct=None,
        )
        pipeline = ImportPipeline(strategy=None)
        result = pipeline._fill_missing_data(product)
        self.assertIsNone(result.discount_pct)

    def test_rounds_discount_correctly(self):
        product = UnifiedProduct(
            name="X", source_id="1", source_type="test",
            price=667, old_price=1000, discount_pct=None,
        )
        pipeline = ImportPipeline(strategy=None)
        result = pipeline._fill_missing_data(product)
        self.assertEqual(result.discount_pct, 33)


class EnrichmentFailureTests(unittest.TestCase):
    """Tests for enrichment failure path."""

    def test_enrichment_failure_returns_no_draft(self):
        """When build_ozon_card_draft raises, enricher returns no draft."""
        product = UnifiedProduct(
            name="Test Product", source_id="123", source_type="test",
            price=1000, description="desc", category="Cat",
        )

        strategy = OzonEnrichmentStrategy()
        with patch("app.enrichers.ozon_enricher.build_ozon_card_draft", side_effect=RuntimeError("boom")):
            result = strategy.enrich(product)

        self.assertIsNone(result.metadata.get("draft"))
        self.assertEqual(result.metadata.get("quality_score"), 0)

    def test_pipeline_enrichment_failure_returns_zero_score(self):
        """Pipeline returns EnrichedProduct with score=0 when enrichment fails."""
        product = UnifiedProduct(
            name="Test Product", source_id="123", source_type="test",
            price=1000, description="desc", category="Cat",
        )

        pipeline = ImportPipeline()
        with patch("app.enrichers.ozon_enricher.build_ozon_card_draft", side_effect=RuntimeError("boom")):
            result = pipeline.run_products([product])

        self.assertEqual(len(result.enriched), 1)
        enriched = result.enriched[0]
        self.assertIsNone(enriched.draft)
        self.assertEqual(enriched.quality_score, 0)
        self.assertEqual(enriched.needs_review, [])
        self.assertEqual(enriched.warnings, [])


class LimitParameterTests(unittest.TestCase):
    """Tests for limit parameter behavior."""

    def test_limit_on_run_file(self):
        csv_content = "name,source_id,price\nA,1,100\nB,2,200\nC,3,300\n"
        from pathlib import Path
        csv_path = Path("/tmp/test_limit.csv")
        csv_path.write_text(csv_content, encoding="utf-8")
        try:
            pipeline = ImportPipeline(limit=2)
            result = pipeline.run_file(csv_path)
            self.assertEqual(len(result.enriched), 2)
        finally:
            csv_path.unlink(missing_ok=True)

    def test_limit_override_in_run_file(self):
        csv_content = "name,source_id,price\nA,1,100\nB,2,200\nC,3,300\n"
        from pathlib import Path
        csv_path = Path("/tmp/test_limit_override.csv")
        csv_path.write_text(csv_content, encoding="utf-8")
        try:
            pipeline = ImportPipeline(limit=3)
            result = pipeline.run_file(csv_path, limit=1)
            self.assertEqual(len(result.enriched), 1)
        finally:
            csv_path.unlink(missing_ok=True)

    def test_limit_none_returns_all(self):
        csv_content = "name,source_id,price\nA,1,100\nB,2,200\n"
        from pathlib import Path
        csv_path = Path("/tmp/test_limit_none.csv")
        csv_path.write_text(csv_content, encoding="utf-8")
        try:
            pipeline = ImportPipeline()
            result = pipeline.run_file(csv_path)
            self.assertEqual(len(result.enriched), 2)
        finally:
            csv_path.unlink(missing_ok=True)

    def test_limit_larger_than_products_returns_all(self):
        csv_content = "name,source_id,price\nA,1,100\nB,2,200\n"
        from pathlib import Path
        csv_path = Path("/tmp/test_limit_big.csv")
        csv_path.write_text(csv_content, encoding="utf-8")
        try:
            pipeline = ImportPipeline(limit=100)
            result = pipeline.run_file(csv_path)
            self.assertEqual(len(result.enriched), 2)
        finally:
            csv_path.unlink(missing_ok=True)


class EmptyProductListTests(unittest.TestCase):
    """Tests for empty product list handling."""

    def test_run_products_empty_list(self):
        pipeline = ImportPipeline()
        result = pipeline.run_products([])
        self.assertIsInstance(result, PipelineResult)
        self.assertEqual(len(result.enriched), 0)
        self.assertEqual(len(result.errors), 0)

    def test_empty_list_enrichment_metadata(self):
        pipeline = ImportPipeline()
        result = pipeline.run_products([])
        self.assertEqual(result.enrichment_metadata["total"], 0)
        self.assertEqual(result.enrichment_metadata["validated"], 0)
        self.assertEqual(result.enrichment_metadata["enriched"], 0)

    def test_empty_list_import_metadata(self):
        pipeline = ImportPipeline()
        result = pipeline.run_products([])
        self.assertEqual(result.import_metadata["source"], "direct")
        self.assertEqual(result.import_metadata["total_products"], 0)


class PluggableStrategyTests(unittest.TestCase):
    """Tests for pluggable enrichment strategy."""

    def test_custom_strategy_is_used(self):
        class DummyStrategy:
            def enrich(self, product):
                from app.enrichers import EnrichmentResult
                return EnrichmentResult(product=product, metadata={"quality_score": 42})

        product = UnifiedProduct(name="X", source_id="1", source_type="test", price=100)
        pipeline = ImportPipeline(strategy=DummyStrategy())
        result = pipeline.run_products([product])
        self.assertEqual(result.enriched[0].quality_score, 42)

    def test_none_strategy_skips_enrichment(self):
        pipeline = ImportPipeline(strategy=None)
        # strategy=None triggers default OzonEnrichmentStrategy
        self.assertIsNotNone(pipeline.strategy)

    def test_enriched_product_with_no_strategy_has_zero_score(self):
        product = UnifiedProduct(name="X", source_id="1", source_type="test", price=100)
        # Manually test _enrich_product with None strategy
        pipeline = ImportPipeline.__new__(ImportPipeline)
        pipeline.strategy = None
        pipeline.validator = type("", (), {"validate": lambda self, p: (p, [])})()
        enriched = pipeline._enrich_product(product)
        self.assertEqual(enriched.quality_score, 0)
        self.assertIsNone(enriched.draft)
        self.assertEqual(enriched.needs_review, [])
        self.assertEqual(enriched.warnings, [])


if __name__ == "__main__":
    unittest.main()
